"""Rebuild standalone public projections.

Dry-run is the default.  A future operator must pass ``--apply --project``
after rules are deployed and the source/target counts have been reviewed.
This script never runs at application startup.
"""

import argparse
import hashlib
import json
import os
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firebase_service import init_firebase
from services.review_service import published_review, commit_feedback, ReviewConflict
from services.campaign_schedule import campaign_package_ids
from sequence_contract.firebase_firestore import deleteRecord, retrieveRecord, storeRecord
from services.public_content_projection import (
    PUBLIC_CAMPAIGN_COLLECTION,
    PUBLIC_PACKAGE_COLLECTION,
    PUBLIC_REVIEW_COLLECTION,
    campaign_publication_eligible,
    eligible_package,
    public_campaign,
    public_package,
    public_review,
)


def rebuild(apply=False):
    packages = retrieveRecord('tourism_packages')
    campaigns = retrieveRecord('promotional_campaigns')
    reviews = retrieveRecord('feedback')
    eligible_packages = {str(item.get('id')): item for item in packages if eligible_package(item)}
    eligible_campaigns = [
        item for item in campaigns
        if campaign_publication_eligible(item) and any(pid in eligible_packages and eligible_packages[pid].get('operatorId') == item.get('operatorId') for pid in campaign_package_ids(item))
    ]
    eligible_reviews = [
        item for item in reviews
        if published_review(item)
    ]
    counts = {
        'packages': len(eligible_packages),
        'campaigns': len(eligible_campaigns),
        'reviews': len(eligible_reviews),
        'removedStale': 0,
        'skippedConcurrentChanges': 0,
    }
    if not apply:
        return counts

    for item in retrieveRecord(PUBLIC_PACKAGE_COLLECTION):
        package_id = str(item.get('id'))
        current = retrieveRecord('tourism_packages', package_id)
        if not eligible_package(current):
            deleteRecord(PUBLIC_PACKAGE_COLLECTION, package_id)
            counts['removedStale'] += 1
    for item in retrieveRecord(PUBLIC_CAMPAIGN_COLLECTION):
        campaign_id = str(item.get('id'))
        current = retrieveRecord('promotional_campaigns', campaign_id)
        parents = [retrieveRecord('tourism_packages', pid) for pid in campaign_package_ids(current or {})]
        current_eligible = bool(current and campaign_publication_eligible(current) and any(eligible_package(p) and p.get('operatorId') == current.get('operatorId') for p in parents))
        if not current_eligible:
            deleteRecord(PUBLIC_CAMPAIGN_COLLECTION, campaign_id)
            counts['removedStale'] += 1
    for item in retrieveRecord(PUBLIC_REVIEW_COLLECTION):
        review_id = str(item.get('id'))
        current = retrieveRecord('feedback', review_id)
        if not published_review(current or {}):
            deleteRecord(PUBLIC_REVIEW_COLLECTION, review_id)
            counts['removedStale'] += 1

    for package_id, package in eligible_packages.items():
        current = retrieveRecord('tourism_packages', package_id)
        if _fingerprint(current) != _fingerprint(package) or not eligible_package(current):
            counts['skippedConcurrentChanges'] += 1
            continue
        profile = retrieveRecord('users', current.get('operatorId')) if current.get('operatorId') else None
        package_campaigns = [
            item for item in eligible_campaigns
            if package_id in campaign_package_ids(item)
        ]
        storeRecord(
            PUBLIC_PACKAGE_COLLECTION,
            public_package(current, profile, package_campaigns),
            package_id,
        )
    for campaign in eligible_campaigns:
        campaign_id = str(campaign.get('id'))
        current = retrieveRecord('promotional_campaigns', campaign_id)
        ids=campaign_package_ids(current or {})
        parents=[retrieveRecord('tourism_packages', pid) for pid in ids]
        valid=[p for p in parents if eligible_package(p) and p.get('operatorId') == (current or {}).get('operatorId')]
        if (_fingerprint(current) != _fingerprint(campaign) or not campaign_publication_eligible(current)
                or not valid or any(_fingerprint(p) != _fingerprint(eligible_packages.get(pid)) for pid,p in zip(ids,parents))):
            counts['skippedConcurrentChanges'] += 1
            continue
        profile = retrieveRecord('users', current.get('operatorId')) if current.get('operatorId') else None
        projected=public_campaign(current, valid[0], profile)
        projected.update(packageIds=[p['id'] for p in valid],packageId=valid[0]['id'])
        storeRecord(PUBLIC_CAMPAIGN_COLLECTION,projected,campaign_id)
    for review in eligible_reviews:
        review_id = str(review.get('id'))
        current = retrieveRecord('feedback', review_id)
        if _fingerprint(current) != _fingerprint(review) or not published_review(current or {}):
            counts['skippedConcurrentChanges'] += 1
            continue
        try:
            commit_feedback(review_id, current, {})
        except ReviewConflict:
            counts['skippedConcurrentChanges'] += 1
    return counts


def _fingerprint(record):
    payload = json.dumps(record or {}, sort_keys=True, default=str, separators=(',', ':'))
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write projections; dry-run is the default')
    parser.add_argument('--project', help='explicit Firebase project id required for writes')
    args = parser.parse_args()
    if args.apply and not args.project:
        parser.error('--project is required with --apply')
    if args.apply:
        os.environ['GOOGLE_CLOUD_PROJECT'] = args.project
    try:
        init_firebase()
        counts = rebuild(apply=args.apply)
        print({'mode': 'apply' if args.apply else 'dry-run', 'eligible': counts})
        return 0
    except Exception as exc:
        print({'mode': 'apply' if args.apply else 'dry-run', 'error': type(exc).__name__}, file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
