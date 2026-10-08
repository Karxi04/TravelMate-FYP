"""Rebuild standalone public projections.

Dry-run is the default.  A future operator must pass ``--apply --project``
after rules are deployed and the source/target counts have been reviewed.
This script never runs at application startup.
"""

import argparse
import os
import sys

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from firebase_service import init_firebase
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
        if campaign_publication_eligible(item) and str(item.get('packageId') or '') in eligible_packages
    ]
    eligible_reviews = [
        item for item in reviews
        if str(item.get('feedbackStatus', 'visible')).lower() == 'visible'
    ]
    counts = {
        'packages': len(eligible_packages),
        'campaigns': len(eligible_campaigns),
        'reviews': len(eligible_reviews),
    }
    if not apply:
        return counts

    package_ids = set(eligible_packages)
    campaign_ids = {str(item.get('id')) for item in eligible_campaigns}
    review_ids = {str(item.get('id')) for item in eligible_reviews}
    for item in retrieveRecord(PUBLIC_PACKAGE_COLLECTION):
        if str(item.get('id')) not in package_ids:
            deleteRecord(PUBLIC_PACKAGE_COLLECTION, item.get('id'))
    for item in retrieveRecord(PUBLIC_CAMPAIGN_COLLECTION):
        if str(item.get('id')) not in campaign_ids:
            deleteRecord(PUBLIC_CAMPAIGN_COLLECTION, item.get('id'))
    for item in retrieveRecord(PUBLIC_REVIEW_COLLECTION):
        if str(item.get('id')) not in review_ids:
            deleteRecord(PUBLIC_REVIEW_COLLECTION, item.get('id'))

    for package_id, package in eligible_packages.items():
        profile = retrieveRecord('users', package.get('operatorId')) if package.get('operatorId') else None
        package_campaigns = [
            item for item in eligible_campaigns
            if str(item.get('packageId') or '') == package_id
        ]
        storeRecord(
            PUBLIC_PACKAGE_COLLECTION,
            public_package(package, profile, package_campaigns),
            package_id,
        )
    for campaign in eligible_campaigns:
        package = eligible_packages[str(campaign.get('packageId'))]
        profile = retrieveRecord('users', campaign.get('operatorId')) if campaign.get('operatorId') else None
        storeRecord(
            PUBLIC_CAMPAIGN_COLLECTION,
            public_campaign(campaign, package, profile),
            campaign['id'],
        )
    for review in eligible_reviews:
        storeRecord(PUBLIC_REVIEW_COLLECTION, public_review(review), review['id'])
    return counts


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true', help='write projections; dry-run is the default')
    parser.add_argument('--project', help='explicit Firebase project id required for writes')
    args = parser.parse_args()
    if args.apply and not args.project:
        parser.error('--project is required with --apply')
    if args.apply:
        os.environ['GOOGLE_CLOUD_PROJECT'] = args.project
    init_firebase()
    counts = rebuild(apply=args.apply)
    print({'mode': 'apply' if args.apply else 'dry-run', 'eligible': counts})


if __name__ == '__main__':
    main()
