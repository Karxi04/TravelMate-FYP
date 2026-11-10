from copy import deepcopy
from random import Random
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from google.api_core.exceptions import DataLoss, InvalidArgument
from google.cloud.firestore_v1 import _helpers
from google.cloud.firestore_v1.types import Document

from modules.fr04_hybrid_recommendation import routes
from services.recommendation_snapshot_storage import load_snapshot, write_snapshot
from test_recommendation_relevance import AUTH, UID, repository


class Reference:
    def __init__(self, data, path='recommendation_snapshots/fixture'):
        self.data, self.path = data, path

    def collection(self, name):
        return Reference(self.data, f'{self.path}/{name}')

    def document(self, identity):
        return Reference(self.data, f'{self.path}/{identity}')

    def set(self, record):
        document = Document(name=self.path, fields=_helpers.encode_dict(record))
        assert Document.pb(document).ByteSize() < 1048576
        self.data[self.path] = deepcopy(record)

    def get(self):
        return SimpleNamespace(to_dict=lambda: deepcopy(self.data.get(self.path)))


class Batch:
    def __init__(self):
        self.writes = []

    def set(self, ref, data):
        self.writes.append((ref, data))

    def commit(self):
        for ref, data in self.writes:
            ref.set(data)


@pytest.mark.parametrize('rich', [False, True])
def test_snapshot_keeps_ranked_candidates_and_firestore_incompatible_metadata(rich):
    random = Random(73)
    rows = [{'destinationId': str(i), 'finalScore': 60.5, 'rankNo': i + 1,
             'providerMetadata': {'__vendor__': [[9, 20], [10, 35]], 'x' * 1501: 'value'},
             'description': random.randbytes(6000).hex() if rich else 'Penang heritage'} for i in range(150)]
    record = {'travellerId': 'fixture', 'recommendationGenerationId': 'fixture',
              'recommendationResults': rows}
    raw = Document(name='recommendation_snapshots/fixture', fields=_helpers.encode_dict(record))
    assert (Document.pb(raw).ByteSize() > 1048576) is rich
    data = {}
    ref = Reference(data)
    write_snapshot(SimpleNamespace(batch=Batch), ref, record)
    stored = ref.get().to_dict()
    assert ('recommendationPayloadParts' in stored) is rich
    assert stored['travellerId'] == 'fixture'
    assert load_snapshot(ref, stored) == record
    if rich:
        del data[f'{ref.path}/payload_parts/0']
        with pytest.raises(DataLoss):
            load_snapshot(ref, stored)


@pytest.mark.parametrize('metadata', [object(), {'amount': float('nan')}, {1: 'non-string key'}])
def test_unserializable_metadata_does_not_publish_empty_or_partial_snapshot(metadata):
    ref = Mock()
    with pytest.raises(InvalidArgument, match='snapshot_non_json_metadata'):
        write_snapshot(Mock(), ref, {'recommendationResults': [{'metadata': metadata}]})
    ref.set.assert_not_called()


def test_unknown_python_object_is_rejected_by_firestore_sdk_before_transport():
    with pytest.raises(TypeError):
        _helpers.encode_dict({'recommendationResults': [{'metadata': object()}]})


def test_legacy_inline_snapshot_remains_readable():
    record = {'recommendationResults': [{'destinationId': 'legacy'}]}
    assert load_snapshot(None, record) == record


def test_invalid_argument_logs_fixed_code_and_returns_correlated_failure(client, mock_traveller_auth, caplog, monkeypatch):
    def retrieve(collection, *args, **kwargs):
        if collection == 'travel_preferences':
            return {'interests': ['Culture']} if args else []
        return {
            'destination_cache': [{'destinationId': 'place', 'title': 'Museum', 'address': 'Penang'}],
        }.get(collection, [])

    monkeypatch.setattr(routes, 'retrieveRecord', retrieve)
    monkeypatch.setattr(routes, 'storeRecord', Mock(side_effect=InvalidArgument(
        "field name 'private-uid-private-comment' is reserved")))
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH,
                           json={'destinationArea': 'Penang'})
    assert response.status_code == 503
    assert response.json['requestId'] == response.headers['X-Request-ID']
    assert response.json['requestId'] in caplog.text
    assert 'reason=reserved_field candidates=1' in caplog.text
    assert 'private-uid-private-comment' not in caplog.text + response.text
    assert 'recommendationGenerationId' not in response.json


def test_invalid_provider_cache_metadata_does_not_abort_expansion(
        client, mock_traveller_auth, repository, monkeypatch, caplog):
    repository.store('recommendation_snapshots', {
        'travellerId': UID,
        'requestedDestination': 'Penang',
        'providerHasMore': True,
        'providerNextOffset': 20,
        'providerQueries': ['tourist attractions'],
        'recommendationResults': [
            {'destinationId': 'old', 'title': 'Museum', 'address': 'Penang'},
        ],
    }, 'previous')
    new = {'destinationId': 'new', 'title': 'Heritage Hall', 'address': 'Penang',
           'providerMetadata': {'series': [[9, 20]]}}
    monkeypatch.setenv('SERPAPI_KEY', 'isolated-provider')
    monkeypatch.setattr(routes, '_provider_destinations', lambda *args: [new])
    stored = routes.storeRecord

    def persist(collection, *args, **kwargs):
        if collection == 'destination_cache':
            raise InvalidArgument('Property array contains an invalid nested entity')
        return stored(collection, *args, **kwargs)

    monkeypatch.setattr(routes, 'storeRecord', persist)
    response = client.post('/api/fr4/recommendations/generate', headers=AUTH, json={
        'destinationArea': 'Penang',
        'previousGenerationId': 'previous',
        'expandCandidates': True,
    })
    assert response.status_code == 200
    assert response.json['recommendationGenerationId'] != 'previous'
    assert {'old', 'new'} <= {row['destinationId'] for row in response.json['recommendations']}
    assert 'recommendation_cache_invalid' in caplog.text and 'reason=nested_value' in caplog.text
