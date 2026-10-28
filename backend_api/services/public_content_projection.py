"""Allowlisted public content contracts and Firestore projection sync.

The source collections contain ownership and moderation fields.  Only this
module writes the standalone public collections; the client never receives a
mixed source document.
"""

import os
from datetime import date

from sequence_contract.firebase_firestore import (
    deleteRecord,
    retrieveRecord,
    storeRecord,
)
from services.package_service import normalise_package
from services.review_service import published_review, review_id


PUBLIC_PACKAGE_COLLECTION = 'public_tourism_packages'
PUBLIC_CAMPAIGN_COLLECTION = 'public_promotional_campaigns'
PUBLIC_REVIEW_COLLECTION = 'public_destination_reviews'

_PACKAGE_FIELDS = {
    'schemaVersion', 'title', 'packageTitle', 'shortDescription',
    'fullDescription', 'description', 'destination', 'destinationName',
    'destinationArea', 'category', 'heroImage', 'imageUrl', 'galleryImages',
    'durationDays', 'durationNights', 'currency', 'adultPrice', 'price',
    'childPrice', 'originalPrice', 'promotionalPrice', 'promotionStart',
    'promotionEnd', 'priceBasis', 'taxIncluded', 'taxNotes',
    'minimumTravellers', 'maximumTravellers', 'maxTravellers',
    'departureDates', 'departureLocation', 'meetingPoint', 'departureNotes',
    'itineraryDays', 'highlights', 'inclusions', 'exclusions',
    'accommodationName', 'accommodationCategory', 'roomType',
    'accommodationNotes', 'transportTypes', 'transportNotes',
    'cancellationPolicy', 'refundPolicy', 'bookingTerms', 'importantNotes',
    'whatToBring', 'availabilityStatus', 'validFrom', 'validUntil',
    'createdAt', 'updatedAt',
}
_CAMPAIGN_FIELDS = {
    'campaignTitle', 'description', 'packageId', 'startDate', 'endDate',
    'campaignStatus', 'discountType', 'discountValue', 'promoCode',
    'bannerImageUrl', 'termsConditions', 'packageTitle', 'destinationName',
    'packagePrice', 'packageImageUrl',
}
_REVIEW_FIELDS = {
    'destinationId', 'destinationName', 'destinationAddress', 'rating',
    'comment', 'travellerName', 'submittedAt', 'updatedAt', 'source',
}


def _public_operator_summary(profile=None, source=None):
    profile = profile or {}
    source = source or {}
    result = {
        'operatorName': (
            profile.get('companyName') or profile.get('businessName')
            or profile.get('name') or source.get('operatorName')
            or 'TravelMate Tourism Operator'
        ),
    }
    # Only explicitly business-labelled contact fields are public.  Auth
    # email/phone fallbacks are deliberately excluded.
    business_email = profile.get('businessEmail') or source.get('businessEmail')
    business_phone = profile.get('businessContact') or source.get('businessContact')
    if business_email:
        result['operatorEmail'] = str(business_email)
    if business_phone:
        result['operatorPhone'] = str(business_phone)
    return result


def public_package(source, operator_profile=None, campaigns=None):
    package = normalise_package(source or {})
    result = {'id': str((source or {}).get('id') or '')}
    result.update({key: package[key] for key in _PACKAGE_FIELDS if key in package})
    result.update({key: source[key] for key in ('createdAt', 'updatedAt') if key in source})
    result.update(_public_operator_summary(operator_profile, source))
    if campaigns is not None:
        result['activeCampaigns'] = [public_campaign(item, package=source) for item in campaigns]
    return {key: value for key, value in result.items() if value not in (None, '')}


def public_campaign(source, package=None, operator_profile=None):
    source = source or {}
    result = {'id': str(source.get('id') or '')}
    result.update({key: source[key] for key in _CAMPAIGN_FIELDS if key in source})
    if package:
        normalized = normalise_package(package)
        result.update({
            'packageTitle': normalized.get('title') or normalized.get('packageTitle'),
            'destinationName': normalized.get('destination') or normalized.get('destinationName'),
            'packagePrice': normalized.get('adultPrice') or normalized.get('price'),
            'packageImageUrl': normalized.get('heroImage') or normalized.get('imageUrl') or '',
        })
    result.update(_public_operator_summary(operator_profile, source))
    return {key: value for key, value in result.items() if value not in (None, '')}


def public_review(source):
    source = source or {}
    result = {
        'id': str(source.get('id') or ''),
        **{key: source[key] for key in _REVIEW_FIELDS if key in source},
        'source': 'travelmate',
    }
    result['username'] = str(source.get('travellerName') or 'Traveller')
    if published_review(source):
        result['publicationStatus'] = 'approved'
    if source.get('travellerId') and source.get('destinationId'):
        result['reviewKey'] = review_id(source['travellerId'], source['destinationId'])
    result['description'] = str(source.get('comment') or '')
    result['date'] = source.get('updatedAt') or source.get('submittedAt') or ''
    return {key: value for key, value in result.items() if value not in (None, '')}


def active_campaign(source, today=None):
    source = source or {}
    if not campaign_publication_eligible(source):
        return False
    today = today or date.today().isoformat()
    start, end = str(source.get('startDate') or ''), str(source.get('endDate') or '')
    return not (start and today < start) and not (end and today > end)


def campaign_publication_eligible(source):
    source = source or {}
    return (
        str(source.get('reviewStatus', '')).lower() == 'approved'
        and str(source.get('campaignStatus', 'approved')).lower() in {'approved', 'active'}
    )


def eligible_package(source):
    return bool(source) and str(source.get('approvalStatus', '')).lower() == 'approved' and str(
        source.get('availabilityStatus', 'available')
    ).lower() == 'available'


def _writes_enabled():
    # Unit tests replace source persistence with deterministic memory stores.
    # Projection writes are exercised separately and must never touch a live
    # Firebase project during the ordinary suite.
    return os.getenv('TRAVELMATE_TESTING', '').lower() not in {'1', 'true', 'yes', 'on'}


def sync_package(package_id, source=None):
    if not _writes_enabled():
        return
    deleteRecord(PUBLIC_PACKAGE_COLLECTION, package_id)
    source = source if source is not None else retrieveRecord('tourism_packages', package_id)
    if not eligible_package(source):
        sync_campaigns_for_package(package_id)
        return
    profile = retrieveRecord('users', source.get('operatorId')) if source.get('operatorId') else None
    campaigns = [
        item for item in retrieveRecord('promotional_campaigns')
        if str(item.get('packageId') or '') == str(package_id) and campaign_publication_eligible(item)
    ]
    storeRecord(
        PUBLIC_PACKAGE_COLLECTION,
        public_package(source, operator_profile=profile, campaigns=campaigns),
        package_id,
    )
    sync_campaigns_for_package(package_id)


def sync_campaign(campaign_id, source=None):
    if not _writes_enabled():
        return
    deleteRecord(PUBLIC_CAMPAIGN_COLLECTION, campaign_id)
    source = source if source is not None else retrieveRecord('promotional_campaigns', campaign_id)
    package_id = str((source or {}).get('packageId') or '')
    package = retrieveRecord('tourism_packages', package_id) if package_id else None
    if not source or not package or not eligible_package(package) or not campaign_publication_eligible(source):
        return
    profile = retrieveRecord('users', source.get('operatorId')) if source.get('operatorId') else None
    storeRecord(
        PUBLIC_CAMPAIGN_COLLECTION,
        public_campaign(source, package=package, operator_profile=profile),
        campaign_id,
    )


def sync_campaigns_for_package(package_id):
    if not _writes_enabled():
        return
    for item in retrieveRecord('promotional_campaigns'):
        if str(item.get('packageId') or '') == str(package_id):
            sync_campaign(item.get('id'), item)


def sync_review(review_id, source=None):
    if not _writes_enabled():
        return
    deleteRecord(PUBLIC_REVIEW_COLLECTION, review_id)
    source = source if source is not None else retrieveRecord('feedback', review_id)
    if not source or not published_review(source):
        return
    from services.review_service import commit_feedback
    commit_feedback(review_id, source, {})


def revoke_projection(collection, document_id):
    """Remove public visibility before a source mutation is committed."""
    if not _writes_enabled():
        return
    if collection == 'tourism_packages':
        deleteRecord(PUBLIC_PACKAGE_COLLECTION, document_id)
        for item in retrieveRecord('promotional_campaigns'):
            if str(item.get('packageId') or '') == str(document_id):
                deleteRecord(PUBLIC_CAMPAIGN_COLLECTION, item.get('id'))
    elif collection == 'promotional_campaigns':
        deleteRecord(PUBLIC_CAMPAIGN_COLLECTION, document_id)
    elif collection == 'feedback':
        deleteRecord(PUBLIC_REVIEW_COLLECTION, document_id)


def source_changed(collection, document_id, source=None):
    if collection == 'tourism_packages':
        sync_package(document_id, source)
    elif collection == 'promotional_campaigns':
        sync_campaign(document_id, source)
    elif collection == 'feedback':
        sync_review(document_id, source)
