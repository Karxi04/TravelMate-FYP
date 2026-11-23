"""Presentation/grouping only: actual portal routes, mocked reads, no real data writes."""
import re
from copy import deepcopy
from html import unescape
from html.parser import HTMLParser
from unittest.mock import MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest

from test_admin_approval_availability import app, auth_client, _patch_admin_api


CATEGORIES = ['flagged','needs_review','automatic','manual','hidden','rejected']
SOURCES = ['traveller','fyp_penang','fyp_regional']
GROUPS = {'all':set(CATEGORIES),'queue':{'flagged','needs_review'},
          'normal':{'automatic','manual'},'hidden_rejected':{'hidden','rejected'}}


def review(source, category, identity=None):
    return {'id':identity or source+'-'+category,'reviewSource':source,'synthetic':source!='traveller',
            'dataset':'fyp-malaysia-coverage-v1' if source!='traveller' else None,
            'reviewProvenance':{'kind':'evaluation' if source!='traveller' else 'genuine'},
            'moderationCategory':category,'rating':4,'destinationName':
            'Penang Hill' if category in {'flagged','automatic','hidden'} else 'Kek Lok Si',
            'destinationAddress':'Penang, Malaysia','travellerName':'Mira Example',
            'submittedAt':'2026-11-10T10:15:00Z','comment':'Beautiful views.\nA peaceful visit.',
            'screening':{'risk':'low','reason':'rating_comment_compatible',
                         'sentiment':{'label':'positive','ratingAlignment':'compatible'}},
            'moderationDecision':{'actor':'administrator','outcome':'approve','at':'2026-11-11T10:00:00Z'},
            'reviewRevision':'revision-'+category,'updatedAt':'2026-11-11T10:00:00Z',
            'reviewComment':'Existing decision note', 'moderationWritable':True,
            'moderationActions':['restore'] if category in {'hidden','rejected'} else
                                ['hide','reverse'] if category in {'automatic','manual'} else ['keep','reject','hide']}


@pytest.fixture
def review_data():
    rows = [review(source,category) for source in SOURCES for category in CATEGORIES]
    before = deepcopy(rows)
    response = MagicMock(ok=True,status_code=200)
    response.json.side_effect = lambda:{'items':rows}
    api = MagicMock(return_value=response)
    with _patch_admin_api(api):
        yield rows, api
    assert rows == before
    assert all(call.args[0]=='GET' for call in api.call_args_list)


def ids(html):
    return re.findall(r'data-review-id="([^"]+)"',html)


class Text(HTMLParser):
    def __init__(self,html):
        super().__init__()
        self.parts=[]
        self.feed(html)
    def handle_data(self,data):
        self.parts.append(data)
    def visible(self):
        return ' '.join(' '.join(self.parts).split())


def test_cards_have_no_source_row_or_substitute_and_keep_review_details(auth_client, review_data):
    page = auth_client.get('/admin/feedback?status=all')
    assert page.status_code==200
    assert 'Traveller feedback and fictional evaluation reviews' in page.text
    assert 'id="review-source"' in page.text
    cards = re.findall(r'<article\b[^>]*class="card review-card"[^>]*>.*?</article>',page.text,re.S)
    assert len(cards)==18
    for card,row in zip(cards,review_data[0]):
        visible = Text(card).visible()
        for forbidden in ['FYP evaluation contribution','fictional','Sample review','Traveller review',
                          'Genuine Traveller feedback','fyp-malaysia-coverage-v1','Read-only fixture']:
            assert forbidden.casefold() not in visible.casefold()
        assert 'fyp-malaysia-coverage-v1' not in card
        # Destination is the next element directly after the status/rating header.
        assert re.search(r'</strong>\s*</div>\s*<h3\b',card)
        for value in [row['destinationName'],'Penang, Malaysia','Mira Example','2026-11-10',
                      'Beautiful views. A peaceful visit.','4 / 5','Screening reason: rating comment compatible',
                      'Decision history','Existing decision note','Moderation note']:
            assert value in visible
        assert 'data-review-source="'+row['reviewSource']+'"' in card
        assert 'name="source" value="'+row['reviewSource']+'"' in card
        assert 'name="expectedRevision" value="'+row['reviewRevision']+'"' in card
        assert 'name="decision"' in card


@pytest.mark.parametrize('status',list(GROUPS))
@pytest.mark.parametrize('source',['all','traveller','evaluation','fyp_penang','fyp_regional'])
@pytest.mark.parametrize('query',['','Penang'])
def test_groups_combine_with_source_and_search_without_mutating(auth_client, review_data, status, source, query):
    rows,api = review_data
    page = auth_client.get('/admin/feedback',query_string={'status':status,'review_source':source,'q':query})
    expected = [row['id'] for row in rows if row['moderationCategory'] in GROUPS[status]
                and (source=='all' or source=='evaluation' and row['synthetic'] or row['reviewSource']==source)
                and (not query or query in row['destinationName'])]
    assert page.status_code==200 and ids(page.text)==expected
    options = re.search(r'<select[^>]*id="review-status"[^>]*>(.*?)</select>',page.text,re.S).group(1)
    assert re.findall(r'<option value="([^"]+)"[^>]*>([^<]+)</option>',options)==[
        ('all','All Reviews'),('queue','Needs Attention'),('normal','Approved'),('hidden_rejected','Hidden / Rejected')]
    assert re.search(r'<option value="'+status+r'"\s+selected',options)
    assert 'name="q" type="search" value="'+query+'"' in page.text
    api.assert_called_once_with('GET','/api/fr13/feedback',params={'source':'all'})


@pytest.mark.parametrize('status',['', '?status=queue','?status=invalid'])
def test_needs_attention_default_and_invalid_filter_fallback(auth_client, review_data, status):
    page = auth_client.get('/admin/feedback'+status)
    expected = {row['id'] for row in review_data[0] if row['moderationCategory'] in GROUPS['queue']}
    assert set(ids(page.text))==expected
    assert '<option value="queue" selected' in page.text


def test_empty_search_does_not_return_unrelated_reviews(auth_client, review_data):
    page = auth_client.get('/admin/feedback?status=all&q=no-such-review')
    assert page.status_code==200 and ids(page.text)==[]
    assert 'No reviews match these filters.' in page.text


@pytest.mark.parametrize('status',CATEGORIES)
def test_historical_category_urls_keep_exact_subset(auth_client, review_data, status):
    page = auth_client.get('/admin/feedback',query_string={'status':status})
    assert set(ids(page.text))=={row['id'] for row in review_data[0] if row['moderationCategory']==status}
    group = next(key for key in ['queue','normal','hidden_rejected'] if status in GROUPS[key])
    assert '<option value="'+group+'" selected' in page.text
    assert 'Select a group above to view all its statuses.' in page.text


def test_group_pagination_keeps_source_search_and_all_records(auth_client):
    rows = [review('fyp_regional','hidden' if i%2 else 'rejected','r'+str(i)) for i in range(125)]
    for row in rows:
        row['destinationName']='Penang Hill'
    before = deepcopy(rows)
    response = MagicMock(ok=True);response.json.return_value={'items':rows}
    api = MagicMock(return_value=response)
    seen=[]
    with _patch_admin_api(api):
        for number in [1,2,3]:
            page = auth_client.get('/admin/feedback',query_string={
                'status':'hidden_rejected','review_source':'evaluation','q':'Penang','page':number})
            seen.extend(ids(page.text))
            links = re.findall(r'href="([^"]+)"[^>]*>(?:Next|Previous)</a>',page.text)
            assert links
            for href in links:
                args = parse_qs(urlsplit(unescape(href)).query)
                assert args['status']==['hidden_rejected'] and args['review_source']==['evaluation'] and args['q']==['Penang']
    assert seen==[row['id'] for row in rows] and len(set(seen))==125
    assert rows==before and all(call.args[0]=='GET' for call in api.call_args_list)


@pytest.mark.parametrize('source',SOURCES)
def test_history_and_restore_keep_source_revision_and_group_redirect(auth_client, source):
    row = review(source,'hidden')
    history = [{'actor':'administrator','outcome':'hide','note':'Earlier review decision','at':'2026-11-11'}]
    def api(method,path,**kwargs):
        response = MagicMock(ok=True,status_code=200)
        response.json.return_value = {'items':history if path.endswith('/history') else [row]}
        return response
    proxy = MagicMock(side_effect=api)
    with _patch_admin_api(proxy):
        page = auth_client.get('/admin/feedback',query_string={
            'status':'hidden_rejected','history':row['id'],'history_source':source})
        assert '<details open>' in page.text and 'Earlier review decision' in page.text
        assert 'Restore and approve' in page.text
        result = auth_client.post('/admin/feedback/'+row['id']+'/review',data={
            'source':source,'decision':'restore','comment':'Restore after review','expectedRevision':row['reviewRevision'],
            'status':'hidden_rejected','review_source':'evaluation' if source!='traveller' else 'traveller','q':'Penang','page':'2'})
    assert result.status_code==302
    args = parse_qs(urlsplit(result.location).query)
    assert args['status']==['hidden_rejected'] and args['page']==['2'] and args['q']==['Penang']
    call = proxy.call_args
    assert call.args==('POST','/api/fr13/feedback/'+row['id']+'/review')
    assert call.kwargs['json']['expectedRevision']==row['reviewRevision']
    assert call.kwargs['json']['decision']=='restore'
    assert call.kwargs.get('params',{})==({'source':source} if source!='traveller' else {})
