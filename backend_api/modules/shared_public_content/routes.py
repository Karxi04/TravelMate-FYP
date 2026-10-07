from datetime import date

from flask import Blueprint, jsonify

from auth_utils import auth_required
from sequence_contract.firebase_firestore import retrieveRecord
from services.package_service import package_for_read

bp = Blueprint('shared_public_content', __name__, url_prefix='/api/public')


def _operator_summary(operator_id):
    if not operator_id:
        return {}
    profile = retrieveRecord('users', operator_id) or {}
    return {
        'operatorName': profile.get('companyName') or profile.get('businessName') or profile.get('name') or 'TravelMate Tourism Operator',
        'operatorEmail': profile.get('businessEmail') or profile.get('email') or '',
        'operatorPhone': profile.get('businessContact') or profile.get('phoneNo') or profile.get('phone') or '',
    }


def _public_campaign(campaign):
    return {
        key: value for key, value in campaign.items()
        if key not in {'operatorId', 'reviewedBy', 'reviewComment', 'reviewStatus'}
    }


def _active_campaign(item):
    if str(item.get('reviewStatus', '')).lower() != 'approved':
        return False
    if str(item.get('campaignStatus', 'approved')).lower() not in {'approved', 'active'}:
        return False
    today = date.today().isoformat()
    start = str(item.get('startDate') or '')
    end = str(item.get('endDate') or '')
    if start and today < start:
        return False
    if end and today > end:
        return False
    return True


@bp.get('/tourism-packages')
@auth_required(['traveller'])
def tourism_packages():
    packages = retrieveRecord('tourism_packages', filters=[('approvalStatus', '==', 'approved')])
    campaigns = [x for x in retrieveRecord('promotional_campaigns', filters=[('reviewStatus', '==', 'approved')]) if _active_campaign(x)]
    campaigns_by_package = {}
    for campaign in campaigns:
        package_id = str(campaign.get('packageId') or '')
        if package_id:
            campaigns_by_package.setdefault(package_id, []).append(campaign)

    visible = []
    for package in packages:
        if str(package.get('availabilityStatus', 'available')).lower() != 'available':
            continue
        item = package_for_read(package)
        item.update(_operator_summary(item.get('operatorId')))
        item['activeCampaigns'] = [
            _public_campaign(campaign)
            for campaign in campaigns_by_package.get(str(item.get('id') or ''), [])
        ]
        for internal in ('operatorId', 'approvalStatus', 'reviewedBy', 'reviewedByName', 'reviewReason', 'reviewComment'):
            item.pop(internal, None)
        visible.append(item)

    visible.sort(key=lambda x: str(x.get('updatedAt') or x.get('createdAt') or ''), reverse=True)
    return jsonify({'ok': True, 'items': visible, 'source': 'firestore'})


@bp.get('/promotional-campaigns')
@auth_required(['traveller'])
def promotional_campaigns():
    campaigns = [x for x in retrieveRecord('promotional_campaigns', filters=[('reviewStatus', '==', 'approved')]) if _active_campaign(x)]
    packages = {str(x.get('id')): x for x in retrieveRecord('tourism_packages', filters=[('approvalStatus', '==', 'approved')])}
    visible = []
    for campaign in campaigns:
        item = _public_campaign(campaign)
        package = packages.get(str(item.get('packageId') or ''))
        if package:
            package = package_for_read(package)
            item['packageTitle'] = package.get('title')
            item['destinationName'] = package.get('destination')
            item['packagePrice'] = package.get('adultPrice')
            item['packageImageUrl'] = package.get('heroImage') or ''
        item.update(_operator_summary(campaign.get('operatorId')))
        visible.append(item)
    visible.sort(key=lambda x: str(x.get('startDate') or ''))
    return jsonify({'ok': True, 'items': visible, 'source': 'firestore'})
