import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';

/// Shared Firestore data that must be consistent across Traveller, Operator and
/// Administrator applications even when the Traveller app is not connected to
/// a local Flask server.
///
/// Operator/Admin writes still go through the Flask backend. The Traveller app
/// only reads approved operator content and reads/writes Traveller feedback.
class SharedFirestoreService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;

  String get _uid => FirebaseAuth.instance.currentUser?.uid ?? '';

  Map<String, dynamic> _doc(QueryDocumentSnapshot<Map<String, dynamic>> d) {
    return {'id': d.id, ...d.data()};
  }

  Future<List<Map<String, dynamic>>> approvedPackages() async {
    final snap = await _db
        .collection('tourism_packages')
        .where('approvalStatus', isEqualTo: 'approved')
        .get();
    final items = snap.docs.map(_doc).where((item) {
      return (item['availabilityStatus'] ?? 'available').toString() == 'available';
    }).toList();
    items.sort((a, b) {
      final ad = (a['updatedAt'] ?? a['createdAt'] ?? '').toString();
      final bd = (b['updatedAt'] ?? b['createdAt'] ?? '').toString();
      return bd.compareTo(ad);
    });
    return items;
  }

  Future<List<Map<String, dynamic>>> approvedCampaigns() async {
    final snap = await _db
        .collection('promotional_campaigns')
        .where('reviewStatus', isEqualTo: 'approved')
        .get();
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final items = snap.docs.map(_doc).where((item) {
      final status = (item['campaignStatus'] ?? 'approved').toString().toLowerCase();
      if (!{'approved', 'active'}.contains(status)) return false;
      final startText = (item['startDate'] ?? '').toString();
      final endText = (item['endDate'] ?? '').toString();
      final start = DateTime.tryParse(startText);
      final end = DateTime.tryParse(endText);
      if (start != null && today.isBefore(DateTime(start.year, start.month, start.day))) return false;
      if (end != null && today.isAfter(DateTime(end.year, end.month, end.day))) return false;
      return true;
    }).toList();

    final packageSnap = await _db
        .collection('tourism_packages')
        .where('approvalStatus', isEqualTo: 'approved')
        .get();
    final packages = <String, Map<String, dynamic>>{
      for (final d in packageSnap.docs) d.id: {'id': d.id, ...d.data()}
    };
    for (final item in items) {
      final package = packages[(item['packageId'] ?? '').toString()];
      if (package != null) {
        item['packageTitle'] = package['packageTitle'];
        item['destinationName'] = package['destinationName'];
        item['packagePrice'] = package['price'];
        item['packageImageUrl'] = package['imageUrl'] ?? package['bannerImageUrl'] ?? '';
      }
    }

    items.sort((a, b) {
      final ad = (a['startDate'] ?? '').toString();
      final bd = (b['startDate'] ?? '').toString();
      return ad.compareTo(bd);
    });
    return items;
  }

  Future<List<Map<String, dynamic>>> destinationReviews(String destinationId) async {
    if (destinationId.trim().isEmpty) return [];
    final snap = await _db
        .collection('feedback')
        .where('feedbackStatus', isEqualTo: 'visible')
        .get();
    final items = snap.docs.map(_doc).where((item) {
      return (item['destinationId'] ?? '').toString() == destinationId;
    }).toList();
    items.sort((a, b) {
      final ad = (a['updatedAt'] ?? a['submittedAt'] ?? '').toString();
      final bd = (b['updatedAt'] ?? b['submittedAt'] ?? '').toString();
      return bd.compareTo(ad);
    });
    return items;
  }


  Future<List<Map<String, dynamic>>> visibleReviews() async {
    final snap = await _db
        .collection('feedback')
        .where('feedbackStatus', isEqualTo: 'visible')
        .get();
    return snap.docs.map(_doc).toList();
  }

  Future<List<Map<String, dynamic>>> ownReviews() async {
    if (_uid.isEmpty) return [];
    final snap = await _db
        .collection('feedback')
        .where('travellerId', isEqualTo: _uid)
        .get();
    final items = snap.docs.map(_doc).toList();
    items.sort((a, b) {
      final ad = (a['updatedAt'] ?? a['submittedAt'] ?? '').toString();
      final bd = (b['updatedAt'] ?? b['submittedAt'] ?? '').toString();
      return bd.compareTo(ad);
    });
    return items;
  }

  Future<Map<String, dynamic>> createReview(Map<String, dynamic> payload) async {
    if (_uid.isEmpty) throw Exception('Please sign in before submitting a review.');
    final user = FirebaseAuth.instance.currentUser;
    final now = DateTime.now().toUtc().toIso8601String();
    final data = <String, dynamic>{
      ...payload,
      'travellerId': _uid,
      'travellerName': (payload['travellerName'] ?? user?.displayName ?? user?.email?.split('@').first ?? 'Traveller').toString(),
      'feedbackStatus': 'visible',
      'moderationStatus': 'pending_review',
      'submittedAt': now,
      'updatedAt': now,
    };
    final ref = await _db.collection('feedback').add(data);
    return {'id': ref.id, ...data};
  }

  Future<Map<String, dynamic>> updateReview(String id, Map<String, dynamic> changes) async {
    if (_uid.isEmpty) throw Exception('Please sign in before updating a review.');
    final ref = _db.collection('feedback').doc(id);
    final current = await ref.get();
    if (!current.exists || (current.data()?['travellerId'] ?? '').toString() != _uid) {
      throw Exception('Review not found.');
    }
    if ((current.data()?['feedbackStatus'] ?? 'visible').toString() == 'removed') {
      throw Exception('This review was removed by the Administrator and cannot be republished by editing it.');
    }
    final updates = <String, dynamic>{
      ...changes,
      'feedbackStatus': 'visible',
      'moderationStatus': 'pending_review',
      'updatedAt': DateTime.now().toUtc().toIso8601String(),
    };
    await ref.update(updates);
    return {'id': id, ...current.data()!, ...updates};
  }

  Future<void> deleteReview(String id) async {
    if (_uid.isEmpty) throw Exception('Please sign in before deleting a review.');
    final ref = _db.collection('feedback').doc(id);
    final current = await ref.get();
    if (!current.exists || (current.data()?['travellerId'] ?? '').toString() != _uid) {
      throw Exception('Review not found.');
    }
    await ref.delete();
  }
}
