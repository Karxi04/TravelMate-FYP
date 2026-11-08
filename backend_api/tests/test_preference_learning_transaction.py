"""Validate the real Firestore adapter with a serializable, offline SDK double."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from threading import Lock
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from sequence_contract.firebase_firestore import transactPreferenceLearning
from services.preference_learning import apply_explicit_feedback


class TransactionDatabase:
    def __init__(self):
        self.records={}
        self.lock=Lock()
        self.fail_audit=False
        self.writes=0
    def collection(self,name):
        database=self
        def document(key):
            def get(transaction=None):
                assert transaction is not None
                value=deepcopy(database.records.get((name,key)))
                return SimpleNamespace(exists=value is not None,to_dict=lambda:value)
            return SimpleNamespace(key=(name,key),get=get)
        return SimpleNamespace(document=document)
    def transaction(self):
        database=self
        staged={}
        def create(ref,data):
            if database.fail_audit:raise RuntimeError('Audit unavailable')
            assert ref.key not in database.records
            staged[ref.key]=deepcopy(data)
        return SimpleNamespace(staged=staged,set=lambda ref,data:staged.update({ref.key:deepcopy(data)}),create=create)
    def transactional(self,fn):
        def commit(tx):
            with self.lock:
                result=fn(tx)
                self.records.update(tx.staged)
                self.writes+=len(tx.staged)
                return result
        return commit


def test_atomic_learning_preserves_two_feedback_writers_idempotency_and_audit_rollback():
    db=TransactionDatabase()
    def feedback(destination,concept):
        return transactPreferenceLearning('owner',lambda current:apply_explicit_feedback(current,
            user_id='owner',destination_id=destination,feedback_type='more_like_this',
            destination_concepts=[concept],event_id=destination,now='2026-11-08T00:00:00Z'))
    with patch('sequence_contract.firebase_firestore.get_db',return_value=db), \
         patch('google.cloud.firestore.transactional',side_effect=db.transactional):
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(feedback,'museum','culture'),executor.submit(feedback,'restaurant','food')]
            for future in futures:future.result()
        profile=db.records[('learned_preference_profiles','owner')]
        assert profile['affinities']=={'culture':.15,'food':.15}
        assert len(profile['feedbackByDestination'])==2
        assert db.writes==4
        assert feedback('museum','culture')[2] is False and db.writes==4
        before=deepcopy(db.records)
        db.fail_audit=True
        with pytest.raises(RuntimeError):feedback('garden','nature')
        assert db.records==before
        db.records[('learned_preference_profiles','owner')]['travellerId']='other'
        with pytest.raises(ValueError):feedback('garden','nature')
