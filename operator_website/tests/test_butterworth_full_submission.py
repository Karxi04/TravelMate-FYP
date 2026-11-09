"""Real Operator HTML/form callbacks bridged to a separate isolated Flask backend."""
from copy import deepcopy
from html import unescape
import json
import os
from pathlib import Path
import re
import subprocess
from unittest.mock import patch

import pytest
from test_package_form_contract import auth_client, app

ROOT=Path(__file__).resolve().parents[2]
FIXTURE=ROOT/'backend_api/tests/fixtures/butterworth_full_original_editor.json'


@pytest.mark.parametrize('editing',[False,True])
@pytest.mark.parametrize('guide',[False,True])
def test_full_original_portal_save_and_submit(auth_client,editing,guide):
    fixture=json.loads(FIXTURE.read_text(encoding='utf-8'))
    form=deepcopy(fixture['form']);form['guideActivitiesIncluded']='true' if guide else 'false'
    backend_python=next((path for path in (ROOT/'backend_api/.venv/Scripts/python.exe', ROOT/'backend_api/.venv/bin/python') if path.is_file()), None)
    if backend_python is None:
        pytest.skip('The isolated cross-portal bridge requires the prepared backend virtual environment.')
    environment=dict(os.environ, PYTHONUTF8='1',PYTHONIOENCODING='utf-8',PYTHONDONTWRITEBYTECODE='1')
    worker=subprocess.Popen([str(backend_python),'-B',str(ROOT/'backend_api/tests/test_butterworth_full_brochure.py')],
        cwd=ROOT/'backend_api',stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,text=True,encoding='utf-8',env=environment,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    calls=[]
    def command(method,path='',body=None):
        worker.stdin.write(json.dumps({'method':method,'path':path,'body':body},ensure_ascii=False)+'\n');worker.stdin.flush()
        while True:
            line=worker.stdout.readline()
            if not line:raise AssertionError('Isolated backend worker exited unexpectedly')
            if line.startswith('BRIDGE_RESPONSE '):return json.loads(line[len('BRIDGE_RESPONSE '):])
    class Response:
        def __init__(self,value):self.status_code=value['status'];self.ok=self.status_code<400;self.value=value['data']
        def json(self):return self.value
    def call_api(method,path,**kwargs):
        body=kwargs.get('json');value=command(method,path,body);calls.append({'method':method,'path':path,'body':body,'status':value['status']})
        return Response(value)
    globals_=app.view_functions['operator_fr12.new_package'].__globals__
    try:
        with patch.dict(globals_,{'call_api':call_api}):
            if editing:
                with app.test_request_context('/',method='POST',data=form):seed=globals_['_package_payload']()
                command('SEED',body=dict(seed,guideActivitiesIncluded=not guide))
            page=auth_client.get('/packages/isolated-butterworth/edit-page' if editing else '/packages/new')
            html=unescape(page.get_data(as_text=True));assert page.status_code==200
            select=re.search(r'<select id="guideActivitiesIncluded".*?</select>',html,re.S).group()
            assert 'value="true"' in select and 'value="false"' in select
            for name in ('originalPrice','promotionalPrice','promotionStart','promotionEnd'):assert f'name="{name}"' not in html
            response=auth_client.post('/packages/isolated-butterworth/edit-page' if editing else '/packages/new',data=form)
            assert response.status_code==302
            save=next(c for c in reversed(calls) if c['method'] in {'PUT','POST'})
            assert save['status']==(200 if editing else 201),save
            assert [save['body'][k] for k in ('accommodationIncluded','transportIncluded','guideActivitiesIncluded')]==[False,True,guide]
            saved=auth_client.get('/packages/isolated-butterworth/edit-page')
            rendered=unescape(saved.get_data(as_text=True))
            assert form['fullDescription'] in rendered
            for line in form['inclusions'].splitlines()+form['exclusions'].splitlines():assert line in rendered
            select=re.search(r'<select id="guideActivitiesIncluded".*?</select>',rendered,re.S).group()
            assert re.search(r'<option value="'+('true' if guide else 'false')+r'"\s+selected',select)
            response=auth_client.post('/packages/isolated-butterworth/submit')
            assert response.status_code==302
            submitted=next(c for c in reversed(calls) if c['path'].endswith('/submit'))
            assert submitted['status']==(200 if guide else 400),submitted
            state=command('STATE');stored=state['package']
            assert stored['approvalStatus']==('pending' if guide else 'draft')
            assert stored['fullDescription']==form['fullDescription']
            assert stored['inclusions']==form['inclusions'].splitlines() and stored['exclusions']==form['exclusions'].splitlines()
            assert len(stored['itineraryDays'][0]['activities'])==14
            assert state['events'][-1]['flags']=={'accommodationIncluded':False,'transportIncluded':True,'guideActivitiesIncluded':guide}
            if os.getenv('TM_BUTTERWORTH_TRACE_DIR'):
                trace=Path(os.environ['TM_BUTTERWORTH_TRACE_DIR'])
                trace.joinpath(f"route-{'edit' if editing else 'create'}-guide-{guide}.json").write_text(
                    json.dumps({'exportSha256':fixture['sourceSha256'],'formChoices':{k:form[k] for k in ('accommodationIncluded','transportIncluded','guideActivitiesIncluded')},
                                'calls':calls,'persistedState':state},ensure_ascii=False,indent=2),encoding='utf-8')
    finally:
        worker.stdin.close();worker.wait(timeout=15);worker.stdout.close()
