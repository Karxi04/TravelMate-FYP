"""Complete owner export, real isolated routes; no live database or provider."""
import ast
from contextlib import ExitStack
from copy import deepcopy
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from flask import Flask, request

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).parent / 'fixtures/butterworth_full_original_editor.json'
FLAGS = ('accommodationIncluded', 'transportIncluded', 'guideActivitiesIncluded')


def original_fixture():
    return json.loads(FIXTURE.read_text(encoding='utf-8'))


def serialize_original(guide=True):
    tree = ast.parse((ROOT / 'operator_website/modules/fr12_tourism_operator_management/routes.py').read_text(encoding='utf-8'))
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'_optional_float', '_optional_int', '_items', '_package_payload'}]
    namespace = {'request': request}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), 'actual_operator_serialization', 'exec'), namespace)
    form = deepcopy(original_fixture()['form'])
    form['guideActivitiesIncluded'] = 'true' if guide else 'false'
    with Flask('serializer').test_request_context('/', method='POST', data=form):
        return namespace['_package_payload']()


class IsolatedBackend:
    def __init__(self):
        from app import create_app
        from test_fr15_package_checkout_stripe import PaymentMemory
        from modules.fr12_tourism_operator_management import routes
        self.memory, self.events, self.stack = PaymentMemory(), [], ExitStack()
        self.memory.seed('users', 'export-operator', {'role':'operator','status':'active','verificationStatus':'approved'})
        self.stack.enter_context(patch('app.init_firebase'))
        self.app = create_app()
        self.app.config.update(TESTING=True)
        def forbidden(*args, **kwargs):
            raise AssertionError('Live Firebase/provider access forbidden in isolated export reproduction')
        self.stack.enter_context(patch('firebase_service.get_db', side_effect=forbidden))
        self.stack.enter_context(patch('sequence_contract.firebase_firestore.get_db', side_effect=forbidden))
        self.stack.enter_context(patch('auth_utils.auth.verify_id_token', return_value={'uid':'export-operator'}))
        def database():
            profile = self.memory.retrieve('users', 'export-operator')
            return SimpleNamespace(collection=lambda name: SimpleNamespace(document=lambda key: SimpleNamespace(get=lambda: SimpleNamespace(exists=True,to_dict=lambda:profile))))
        self.stack.enter_context(patch('auth_utils.get_db', side_effect=database))
        self.stack.enter_context(patch.object(routes, 'retrieveRecord', side_effect=self.memory.retrieve))
        self.stack.enter_context(patch.object(routes, 'updateRecord', side_effect=self.memory.update))
        def store(collection, data):
            self.memory.seed(collection, 'isolated-butterworth', data)
            return self.memory.retrieve(collection, 'isolated-butterworth')
        self.stack.enter_context(patch.object(routes, 'storeRecord', side_effect=store))
        normalize, validate = routes.normalise_package, routes.package_submission_error
        def normalise(data, existing=None):
            value=normalize(data, existing)
            self.events.append({'stage':'normalization','flags':{k:value.get(k) for k in FLAGS}})
            return value
        def validation(data):
            result=validate(data)
            self.events.append({'stage':'submission_validator','flags':{k:data.get(k) for k in FLAGS},'error':result})
            return result
        self.stack.enter_context(patch.object(routes, 'normalise_package', side_effect=normalise))
        self.stack.enter_context(patch.object(routes, 'package_submission_error', side_effect=validation))
        self.client=self.app.test_client()

    def call(self, method, path, body=None):
        response=self.client.open(path, method=method, json=body, headers={'Authorization':'Bearer isolated-export-token'})
        return {'status':response.status_code,'data':response.get_json(),'allow':response.headers.get('Allow')}

    def seed(self, payload):
        self.memory.seed('tourism_packages','isolated-butterworth',dict(payload, operatorId='export-operator',approvalStatus='draft',originalPrice='269.0'))

    def state(self):
        return {'package':self.memory.retrieve('tourism_packages','isolated-butterworth'),'events':self.events}

    def close(self):
        self.stack.close()


@pytest.fixture
def isolated_export(app):
    backend=IsolatedBackend()
    yield backend
    backend.close()


@pytest.mark.parametrize('editing',[False,True])
@pytest.mark.parametrize('guide',[False,True])
def test_complete_original_create_edit_submit(isolated_export,editing,guide):
    backend=isolated_export;payload=serialize_original(guide)
    assert [payload[k] for k in FLAGS]==[False,True,guide]
    assert len(payload['inclusions'])==9 and len(payload['exclusions'])==11
    assert len(payload['itineraryDays'][0]['activities'])==14
    assert not {'originalPrice','promotionalPrice','promotionStart','promotionEnd'} & payload.keys()
    if editing:backend.seed(dict(payload,guideActivitiesIncluded=not guide))
    saved=backend.call('PUT' if editing else 'POST','/api/fr12/packages'+('/isolated-butterworth' if editing else ''),payload)
    assert saved['status']==(200 if editing else 201),saved
    response=backend.call('POST','/api/fr12/packages/isolated-butterworth/submit')
    assert response['status']==(200 if guide else 400),response
    state=backend.state();stored=state['package']
    assert stored['inclusions']==payload['inclusions'] and stored['exclusions']==payload['exclusions']
    assert stored['fullDescription']==payload['fullDescription'] and stored['itineraryDays']==payload['itineraryDays']
    assert stored['approvalStatus']==('pending' if guide else 'draft')
    assert state['events'][-1]['flags']['guideActivitiesIncluded'] is guide
    if not guide:assert 'guideActivitiesIncluded' in response['data']['error']
    if editing:assert stored['originalPrice']=='269.0'



@pytest.mark.parametrize('extra',[
    'Standard admission ticket to Penang Bird Park is paid separately.',
    'No guide or tour escort is included.',
    'Admission tickets are not included.',
    'Ferry tickets outside the scheduled itinerary and no guide or tour escort is included.',
])
def test_full_brochure_genuine_contradictions_remain_blocked(extra):
    from services.package_service import package_submission_error
    payload=serialize_original()
    payload['exclusions'].append(extra)
    assert 'guideActivitiesIncluded' in package_submission_error(payload)


def test_new_snapshot_requirements_and_historical_versions_are_independent():
    from services.package_checkout_contract import derive_required_services, prepare_package_snapshot, build_initial_fulfillment_record
    payload=serialize_original()
    raw={**payload,'id':'isolated-butterworth','operatorId':'export-operator','approvalStatus':'approved'}
    snapshot=prepare_package_snapshot(raw,{'id':'export-operator'},participants={'adults':4,'children':0},departure_date='2026-11-14',now='2026-11-09')
    assert snapshot['supplierRequirementVersion']==3 and snapshot['price']==916 and snapshot['amountMinor']==91600
    before=deepcopy(snapshot)
    requirements=derive_required_services(snapshot)
    assert not requirements['accommodation']['required'] and not requirements['accommodation']['uncertain']
    assert requirements['transport']['required'] and requirements['guideActivities']['required']
    assert not requirements['transport']['uncertain'] and not requirements['guideActivities']['uncertain']
    initial=build_initial_fulfillment_record(snapshot)
    assert initial['services']['accommodation']['status']=='not_required'
    assert initial['services']['transport']['status']=='unconfirmed'
    assert initial['services']['guideActivities']['status']=='unconfirmed'
    for version in (None,2):
        historical=deepcopy(snapshot)
        if version is None:historical.pop('supplierRequirementVersion')
        else:historical['supplierRequirementVersion']=version
        saved=deepcopy(historical)
        assert derive_required_services(historical)['guideActivities']['uncertain']
        assert historical==saved
    assert snapshot==before

def bridge_main():
    # The portal regression starts this worker with a dedicated process and pipe.
    # No HTTP listener or production authentication is used.
    for name in ('FIREBASE_SERVICE_ACCOUNT','FIREBASE_SERVICE_ACCOUNT_JSON','GOOGLE_APPLICATION_CREDENTIALS','SERPAPI_KEY','LITEAPI_KEY','STRIPE_SECRET_KEY','GEMINI_API_KEY'):
        os.environ[name]=''
    os.environ.update(TRAVELMATE_TESTING='true',FALLBACK_MODE='true',PYTHONDONTWRITEBYTECODE='1')
    import pytest_socket
    pytest_socket.disable_socket()
    backend=IsolatedBackend()
    try:
        for line in sys.stdin:
            command=json.loads(line)
            if command['method']=='SEED':backend.seed(command['body']);result={'ok':True}
            elif command['method']=='STATE':result=backend.state()
            else:result=backend.call(command['method'],command['path'],command.get('body'))
            print('BRIDGE_RESPONSE '+json.dumps(result,ensure_ascii=False),flush=True)
    finally:backend.close()


if __name__=='__main__':
    sys.path[:0]=[str(ROOT/'backend_api'),str(ROOT/'backend_api/tests')]
    bridge_main()
