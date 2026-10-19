from flask import Blueprint, jsonify, send_from_directory
from services.image_storage_service import is_safe_filename, get_upload_dir

from auth_utils import auth_required
from sequence_contract.firebase_firestore import retrieveRecord
from services.public_content_projection import (
    active_campaign,
    eligible_package,
    public_campaign,
    public_package,
)

bp = Blueprint('shared_public_content', __name__, url_prefix='/api/public')


def _operator_summary(operator_id):
    if not operator_id:
        return {}
    profile = retrieveRecord('users', operator_id) or {}
    return profile


@bp.get('/tourism-packages')
@auth_required(['traveller'])
def tourism_packages():
    packages = retrieveRecord('tourism_packages', filters=[('approvalStatus', '==', 'approved')])
    campaigns = [x for x in retrieveRecord('promotional_campaigns', filters=[('reviewStatus', '==', 'approved')]) if active_campaign(x)]
    campaigns_by_package = {}
    for campaign in campaigns:
        package_id = str(campaign.get('packageId') or '')
        if package_id:
            campaigns_by_package.setdefault(package_id, []).append(campaign)

    visible = []
    for package in packages:
        if not eligible_package(package):
            continue
        profile = _operator_summary(package.get('operatorId'))
        item = public_package(package, operator_profile=profile, campaigns=campaigns_by_package.get(str(package.get('id') or ''), []))
        visible.append(item)

    visible.sort(key=lambda x: str(x.get('updatedAt') or x.get('createdAt') or ''), reverse=True)
    return jsonify({'ok': True, 'items': visible, 'source': 'firestore'})


@bp.get('/promotional-campaigns')
@auth_required(['traveller'])
def promotional_campaigns():
    campaigns = [x for x in retrieveRecord('promotional_campaigns', filters=[('reviewStatus', '==', 'approved')]) if active_campaign(x)]
    packages = {str(x.get('id')): x for x in retrieveRecord('tourism_packages') if eligible_package(x)}
    visible = []
    for campaign in campaigns:
        package = packages.get(str(campaign.get('packageId') or ''))
        if not package:
            continue
        item = public_campaign(
            campaign,
            package=package,
            operator_profile=_operator_summary(campaign.get('operatorId')),
        )
        visible.append(item)
    visible.sort(key=lambda x: str(x.get('startDate') or ''))
    return jsonify({'ok': True, 'items': visible, 'source': 'firestore'})


@bp.get('/package-images/<filename>')
def serve_package_image(filename):
    if not is_safe_filename(filename):
        return jsonify({'ok': False, 'error': 'Invalid image filename'}), 400
    upload_dir = get_upload_dir()
    if not (upload_dir / filename).is_file():
        return jsonify({'ok': False, 'error': 'Image not found'}), 404
    response = send_from_directory(str(upload_dir), filename)
    response.headers['Cache-Control'] = 'public, max-age=86400'
    return response

