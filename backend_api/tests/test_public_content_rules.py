from pathlib import Path


RULES = Path(__file__).parents[2] / 'firebase' / 'firestore.rules'


def test_public_content_rules_use_projection_collections_and_deny_sources():
    rules = RULES.read_text(encoding='utf-8')
    assert 'match /public_tourism_packages/{packageId}' in rules
    assert 'match /public_promotional_campaigns/{campaignId}' in rules
    assert 'match /public_destination_reviews/{reviewId}' in rules
    assert 'match /public_tourism_packages/{packageId} {\n      allow read: if signedIn();\n      allow write: if false;' in rules
    assert 'match /tourism_packages/{packageId}' in rules
    assert 'match /promotional_campaigns/{campaignId}' in rules
    assert 'match /tourism_packages/{packageId} {\n      allow read, write: if false;' in rules
    assert 'match /promotional_campaigns/{campaignId} {\n      allow read, write: if false;' in rules
    assert "resource.data.travellerId == request.auth.uid" in rules
