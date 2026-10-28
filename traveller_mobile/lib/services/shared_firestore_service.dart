import 'package:cloud_firestore/cloud_firestore.dart';
import 'package:firebase_auth/firebase_auth.dart';
import 'public_content_contract.dart';
import 'review_contract.dart';

/// Shared Firestore data that must be consistent across Traveller, Operator and
/// Administrator applications even when the Traveller app is not connected to
/// a local Flask server.
///
/// Operator/Admin writes still go through the Flask backend. The Traveller app
/// only reads server-authored public projections and reads/writes Traveller
/// feedback through the owner-authenticated source path.
class SharedFirestoreService {
  final FirebaseFirestore _db = FirebaseFirestore.instance;

  String get _uid => FirebaseAuth.instance.currentUser?.uid ?? '';

  Map<String, dynamic> _doc(QueryDocumentSnapshot<Map<String, dynamic>> d) {
    return {'id': d.id, ...d.data()};
  }

  Future<List<Map<String, dynamic>>> approvedPackages() async {
    final snap = await _db
        .collection('public_tourism_packages')
        .get();
    final items = snap.docs.map((d) => PublicContentContract.package(_doc(d))).where((item) {
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
        .collection('public_promotional_campaigns')
        .get();
    final items = snap.docs
        .map((d) => PublicContentContract.campaign(_doc(d)))
        .where(PublicContentContract.activeCampaign)
        .toList();

    final packageSnap = await _db.collection('public_tourism_packages').get();
    final packages = <String, Map<String, dynamic>>{
      for (final d in packageSnap.docs)
        d.id: PublicContentContract.package(_doc(d))
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

  Future<List<Map<String, dynamic>>> _publicReviews([String? destinationId]) async {
    Query<Map<String, dynamic>> query = _db.collection('public_destination_reviews').where('publicationStatus', isEqualTo: 'approved');
    if (destinationId != null) query = query.where('destinationId', isEqualTo: destinationId);
    final all = <Map<String, dynamic>>[];
    QueryDocumentSnapshot<Map<String, dynamic>>? cursor;
    while (true) {
      final page = await (cursor == null ? query.limit(10) : query.startAfterDocument(cursor).limit(10)).get();
      all.addAll(page.docs.map((d) => PublicContentContract.review(_doc(d))));
      if (page.docs.length < 10) break;
      cursor = page.docs.last;
    }
    all.sort((a, b) => '${b['updatedAt'] ?? ''}'.compareTo('${a['updatedAt'] ?? ''}'));
    final unique = <String, Map<String, dynamic>>{};
    for (final item in all) {
      unique.putIfAbsent('${item['reviewKey'] ?? item['id']}', () => item);
    }
    return unique.values.toList();
  }

  Future<List<Map<String, dynamic>>> destinationReviews(String destinationId) async {
    if (destinationId.trim().isEmpty) return [];
    final items = (await _publicReviews(destinationId)).where((item) {
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
    return _publicReviews();
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
    if (!ReviewContract.valid(payload)) throw Exception('Choose a place, rate it 1–5 and write 5–2000 characters.');
    final user = FirebaseAuth.instance.currentUser;
    final now = DateTime.now().toUtc().toIso8601String();
    final data = <String, dynamic>{
      ...payload,
      'travellerId': _uid,
      'travellerName': user?.displayName ?? 'Traveller',
      'feedbackStatus': 'visible',
      'moderationStatus': 'pending_review',
      'submittedAt': now,
      'updatedAt': now,
    };
    final previous = (await ownReviews()).where((item) => item['destinationId'] == payload['destinationId']).toList();
    final ref = _db.collection('feedback').doc(previous.isEmpty ? ReviewContract.identity(_uid, payload['destinationId']) : previous.first['id']);
    return _db.runTransaction((transaction) async {
      final existing = await transaction.get(ref);
      if (existing.exists) {
        final item = existing.data()!;
        if (item['travellerId'] != _uid || item['feedbackStatus'] == 'removed') throw Exception('This review cannot be resubmitted.');
        if (item['rating'] != payload['rating'] || item['comment'] != payload['comment']) throw Exception('You already reviewed this place. Edit your existing review.');
        return {'id': ref.id, ...item};
      }
      transaction.set(ref, data);
      return {'id': ref.id, ...data};
    });
  }

  Future<Map<String, dynamic>> updateReview(String id, Map<String, dynamic> changes) async {
    if (_uid.isEmpty) throw Exception('Please sign in before updating a review.');
    if (!ReviewContract.valid(changes, partial: true)) throw Exception('Invalid review update.');
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
    final batch = _db.batch();
    batch.update(ref, updates);
    batch.delete(_db.collection('public_destination_reviews').doc(id));
    await batch.commit();
    return {'id': id, ...current.data()!, ...updates};
  }

  Future<void> deleteReview(String id) async {
    if (_uid.isEmpty) throw Exception('Please sign in before deleting a review.');
    final ref = _db.collection('feedback').doc(id);
    final current = await ref.get();
    if (!current.exists || (current.data()?['travellerId'] ?? '').toString() != _uid) {
      throw Exception('Review not found.');
    }
    final batch = _db.batch();
    batch.delete(ref);
    batch.delete(_db.collection('public_destination_reviews').doc(id));
    await batch.commit();
  }
}
