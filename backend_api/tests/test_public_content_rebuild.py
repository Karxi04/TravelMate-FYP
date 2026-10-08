from scripts import rebuild_public_content as rebuild_tool


def test_rebuild_dry_run_performs_no_projection_writes(monkeypatch):
    package = {'id': 'pkg-1', 'approvalStatus': 'approved', 'availabilityStatus': 'available'}
    calls = []

    def retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'tourism_packages':
            return [package] if document_id is None else package
        if collection in {'promotional_campaigns', 'feedback'}:
            return []
        return []

    monkeypatch.setattr(rebuild_tool, 'retrieveRecord', retrieve)
    monkeypatch.setattr(rebuild_tool, 'storeRecord', lambda *args, **kwargs: calls.append(('store', args)))
    monkeypatch.setattr(rebuild_tool, 'deleteRecord', lambda *args, **kwargs: calls.append(('delete', args)))
    result = rebuild_tool.rebuild(apply=False)
    assert result['packages'] == 1
    assert calls == []


def test_rebuild_skips_snapshot_rejected_before_publish(monkeypatch):
    approved_snapshot = {
        'id': 'pkg-1', 'approvalStatus': 'approved', 'availabilityStatus': 'available',
        'updatedAt': 'before',
    }
    rejected_current = {
        **approved_snapshot, 'approvalStatus': 'rejected', 'updatedAt': 'after',
    }
    stored = []

    def retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'tourism_packages':
            return [approved_snapshot] if document_id is None else rejected_current
        if collection in {
            'promotional_campaigns', 'feedback',
            'public_tourism_packages', 'public_promotional_campaigns',
            'public_destination_reviews',
        }:
            return []
        return []

    monkeypatch.setattr(rebuild_tool, 'retrieveRecord', retrieve)
    monkeypatch.setattr(rebuild_tool, 'storeRecord', lambda *args, **kwargs: stored.append(args))
    monkeypatch.setattr(rebuild_tool, 'deleteRecord', lambda *args, **kwargs: None)
    result = rebuild_tool.rebuild(apply=True)
    assert result['skippedConcurrentChanges'] == 1
    assert stored == []


def test_rebuild_cleanup_keeps_newly_eligible_source(monkeypatch):
    package = {'id': 'pkg-1', 'approvalStatus': 'approved', 'availabilityStatus': 'available'}
    deleted = []

    def retrieve(collection, document_id=None, filters=None, limit=None):
        if collection == 'tourism_packages':
            return [package] if document_id is None else package
        if collection == 'public_tourism_packages':
            return [{'id': 'pkg-1'}]
        return []

    monkeypatch.setattr(rebuild_tool, 'retrieveRecord', retrieve)
    monkeypatch.setattr(rebuild_tool, 'storeRecord', lambda *args, **kwargs: None)
    monkeypatch.setattr(rebuild_tool, 'deleteRecord', lambda *args, **kwargs: deleted.append(args))
    rebuild_tool.rebuild(apply=True)
    assert deleted == []
