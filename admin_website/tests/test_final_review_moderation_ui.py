"""Isolated portal/browser -> actual Backend routes -> disposable SQLite."""
import json
import os
import re
import subprocess
from pathlib import Path
from unittest.mock import MagicMock
from urllib.parse import urlencode, urlsplit
import pytest
from test_admin_approval_availability import app, auth_client, _patch_admin_api

ROOT=Path(__file__).resolve().parents[2]


class ReviewWorker:
    def __init__(self,path):
        self.path=path
        self.start()

    def start(self):
        python=ROOT/'backend_api/.venv/Scripts/python.exe'
        self.worker=subprocess.Popen([str(python),'-B',str(ROOT/'backend_api/tests/test_final_review_moderation.py'),str(self.path)],
            cwd=ROOT/'backend_api',stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
            text=True,encoding='utf-8',env={**os.environ,'PYTHONIOENCODING':'utf-8','PYTHONDONTWRITEBYTECODE':'1'},
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
        if not hasattr(self,'calls'):self.calls=[]

    def close(self):
        if self.worker.poll() is None:
            self.worker.stdin.close()
            try:self.worker.wait(timeout=8)
            except subprocess.TimeoutExpired:
                self.worker.terminate();self.worker.wait(timeout=5)

    def api(self,method,path,**kwargs):
        query=urlencode(kwargs.get('params') or {})
        self.worker.stdin.write(json.dumps({'method':method,'path':path+('?' + query if query else ''),'body':kwargs.get('json')})+'\n')
        self.worker.stdin.flush()
        while True:
            line=self.worker.stdout.readline()
            if not line:raise AssertionError('The isolated Backend exited unexpectedly.')
            if line.startswith('BRIDGE_RESPONSE '):break
        value=json.loads(line[len('BRIDGE_RESPONSE '):]);self.calls.append((method,path,value['status']))
        response=MagicMock(ok=value['status']<400,status_code=value['status'])
        response.json.return_value=value['data'];return response


def test_source_filters_and_all_pages_keep_large_dataset_records(auth_client):
    rows=[{'id':f'r{i}','destinationName':f'Place {i}','moderationCategory':'automatic',
           'reviewSource':'traveller' if i%2==0 else 'fyp_regional','synthetic':i%2==1,'moderationWritable':False} for i in range(1200)]
    response=MagicMock(ok=True);response.json.return_value={'items':rows}
    with _patch_admin_api(lambda *_a,**_kw:response):
        seen=[]
        for page in range(1,13):
            html=auth_client.get(f'/admin/feedback?status=all&review_source=evaluation&page={page}').get_data(as_text=True)
            found=re.findall(r'data-review-id="(r\d+)"',html)
            assert len(found)==50
            assert 'FYP evaluation contribution' in html and 'Review source' in html
            seen.extend(found)
        assert len(seen)==len(set(seen))==600
        genuine=auth_client.get('/admin/feedback?status=all&review_source=traveller').get_data(as_text=True)
        assert 'data-review-source="fyp_regional"' not in genuine
        assert 'Genuine Traveller feedback' in genuine


def test_moderation_csrf_rejected_before_backend_proxy(auth_client):
    previous=app.config['WTF_CSRF_ENABLED'];app.config['WTF_CSRF_ENABLED']=True
    try:
        with _patch_admin_api(MagicMock(side_effect=AssertionError('CSRF must stop the request'))):
            assert auth_client.post('/admin/feedback/isolated/review',data={'decision':'restore'}).status_code==400
    finally:app.config['WTF_CSRF_ENABLED']=previous


def test_template_is_readable_before_an_existing_portal_worker_is_reloaded():
    from flask import render_template
    # The protected worker can retain old Python routes while Jinja reads new templates.
    categories={'flagged':'Flagged','needs_review':'Needs review','automatic':'Automatically approved',
                'manual':'Manually approved','hidden':'Hidden'}
    with app.test_request_context('/admin/feedback'):
        html=render_template('fr13_administrator_management/feedback.html',
            items=[{'id':'legacy-review','moderationCategory':'hidden','rating':2,'reviewSource':'traveller'}],
            counts=dict.fromkeys(categories,0),categories=categories,status='hidden',query='',
            history_id='',history=None,history_source='traveller',private_unavailable=False)
    assert 'data-review-id="legacy-review"' in html
    assert 'Restore and approve' not in html and 'Revoke approval' not in html
    assert 'name="review_source"' not in html


@pytest.mark.integration
@pytest.mark.timeout(90)
@pytest.mark.allow_hosts(['127.0.0.1','localhost','::1'])
def test_isolated_browser_moderates_actual_routes_and_reopens_sqlite_history(tmp_path,monkeypatch):
    playwright=pytest.importorskip('playwright.sync_api')
    chrome=Path('C:/Program Files/Google/Chrome/Application/chrome.exe')
    if not chrome.is_file():pytest.skip('Installed Chrome is required for this isolated browser check.')
    temporary=tmp_path/'browser-temp';temporary.mkdir()
    for name in ['TEMP','TMP','TMPDIR']:monkeypatch.setenv(name,str(temporary))
    worker=ReviewWorker(tmp_path/'overlay'/'reviews.sqlite3')
    # Playwright callbacks use a greenlet: do not retain Flask request contexts between callbacks.
    browser_client=app.test_client()
    with browser_client.session_transaction() as session:
        session.update(id_token='isolated-admin-token',portal_role='admin',admin_id='isolated-admin')
    if 'request_rate_limiter' in app.extensions:app.extensions['request_rate_limiter'].reset()
    old_csrf=app.config['WTF_CSRF_ENABLED'];app.config['WTF_CSRF_ENABLED']=True
    try:
        pending=next(r for r in worker.api('GET','/api/fr13/feedback',params={'source':'all'}).json()['items']
                     if r['reviewSource']=='fyp_regional' and r['moderationState']=='pending')
        selector='form[action="/admin/feedback/'+pending['id']+'/review"]'
        def go(page,status):
            page.goto('http://travelmate.test/admin/feedback?'+urlencode({'status':status,'review_source':'fyp_regional','q':pending['destinationName']}))
            page.locator(selector).wait_for()
        with _patch_admin_api(worker.api),playwright.sync_playwright() as driver:
            browser=driver.chromium.launch(executable_path=str(chrome),headless=True,
                args=['--disable-background-networking','--disable-component-update','--disable-sync','--no-first-run'])
            context=browser.new_context()
            def serve(route):
                request=route.request
                if not request.url.startswith('http://travelmate.test/'):
                    route.abort();return
                url=urlsplit(request.url)
                response=browser_client.open(url.path+('?' + url.query if url.query else ''),method=request.method,
                    data=request.post_data,content_type=request.headers.get('content-type'))
                route.fulfill(status=response.status_code,headers={k:v for k,v in response.headers.items()
                    if k.lower() not in {'set-cookie','content-length'}},body=response.get_data())
            context.route('**/*',serve)
            page=context.new_page()
            go(page,'queue')
            page.locator(selector).get_by_role('button',name='Approve',exact=True).click()
            page.wait_for_load_state('networkidle')
            go(page,'manual')
            page.locator(selector).get_by_role('button',name='Hide',exact=True).click()
            page.wait_for_load_state('networkidle')
            go(page,'hidden')
            form=page.locator(selector)
            writes=len([c for c in worker.calls if c[0]=='POST'])
            form.get_by_role('button',name='Restore and approve',exact=True).click()
            assert form.locator('textarea').evaluate('(node)=>node.validity.valueMissing')
            assert len([c for c in worker.calls if c[0]=='POST'])==writes
            form.locator('textarea').fill('Restore after isolated review')
            form.get_by_role('button',name='Restore and approve',exact=True).click()
            page.wait_for_load_state('networkidle')
            go(page,'manual')
            page.locator(selector).locator('textarea').fill('Revoke approval after isolated audit')
            page.locator(selector).get_by_role('button',name='Revoke approval',exact=True).click()
            page.wait_for_load_state('networkidle')
            worker.close();worker.start()  # New Python process, same disposable database.
            go(page,'rejected')
            article=page.locator('article[data-review-id="'+pending['id']+'"]')
            assert 'FYP evaluation contribution' in article.inner_text()
            article.get_by_role('link',name='Decision history').click()
            page.wait_for_load_state('networkidle')
            assert page.locator('details[open]').count()==1
            assert 'revoke' in page.locator('details[open]').inner_text()
            other=next(r for r in worker.api('GET','/api/fr13/feedback',params={'source':'all'}).json()['items']
                       if r['reviewSource']=='fyp_regional' and r['moderationState']=='pending')
            page.goto('http://travelmate.test/admin/feedback?'+urlencode({'status':'queue',
                'review_source':'fyp_regional','q':other['destinationName']}))
            rejected_form=page.locator('form[action="/admin/feedback/'+other['id']+'/review"]')
            rejected_form.get_by_role('button',name='Reject',exact=True).click()
            page.wait_for_load_state('networkidle')
            page.goto('http://travelmate.test/admin/feedback?'+urlencode({'status':'rejected',
                'review_source':'fyp_regional','q':other['destinationName']}))
            assert page.locator('article[data-review-id="'+other['id']+'"]').count()==1
            posts=[status for method,_path,status in worker.calls if method=='POST']
            assert posts==[200,200,200,200,200]
            context.close();browser.close()
    finally:
        app.config['WTF_CSRF_ENABLED']=old_csrf
        worker.close()
