import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../core/utils/destination_utils.dart';
import '../services/api_service.dart';
import '../services/review_contract.dart';
import 'travel_widgets.dart';

/// Presentation only: never substitutes provider scores or changes ranking data.
class LocalReviewRatings {
  static final revision = ValueNotifier<int>(0);
  static Future<Map<String, dynamic>>? _pending;
  static DateTime? _expires;
  static final Map<String, Map<String, dynamic>> _recent = {};
  static final Map<String, DateTime> _recentUntil = {};
  static String _identity = '';
  static String? _recentOwner;

  static String get accountUid {
    try {
      return FirebaseAuth.instance.currentUser?.uid ?? '';
    } catch (_) {
      return '';
    }
  }

  static void _scopeRecent(String owner) {
    if (_recentOwner == owner) return;
    _recentOwner = owner;
    _recent.clear();
    _recentUntil.clear();
  }

  static void invalidate() {
    _pending = null;
    _expires = null;
    _recent.clear();
    _recentUntil.clear();
    revision.value++;
  }

  static void remember(String id, Map<String, dynamic> summary) {
    final owner = accountUid;
    if (owner.isEmpty && summary['fypPreview'] == true) return;
    _scopeRecent(owner);
    final canonical = ReviewContract.destinationId(id);
    _recent[canonical] = {
      'rating': summary['rating'],
      'reviews': summary['reviews'],
      if (summary['fypPreview'] == true) 'fypPreview': true,
    };
    _recentUntil[canonical] = DateTime.now().add(const Duration(seconds: 30));
    revision.value++;
  }

  static Future<Map<String, dynamic>> forPlace(String id,
      {ApiService? api}) async {
    final now = DateTime.now();
    final canonical = ReviewContract.destinationId(id);
    final uid = accountUid;
    _scopeRecent(uid);
    if (_recentUntil[canonical]?.isAfter(now) == true) return _recent[canonical]!;
    if (api == null && uid.isEmpty) return {};
    final identity =
        '$uid|${ApiService.forceStandalone ? 'standalone' : ApiService.baseUrl}|${api == null ? 0 : identityHashCode(api)}';
    if (_identity != identity || _expires?.isAfter(now) != true) {
      _identity = identity;
      _expires = now.add(const Duration(seconds: 30));
      _pending = (api ?? ApiService())
          .get('/api/fr3/local-ratings')
          .then(
              (data) => Map<String, dynamic>.from(data['items'] as Map? ?? {}))
          .catchError((_) => <String, dynamic>{});
    }
    final summaries = await _pending!;
    if (accountUid != uid) return {};
    final summary = summaries[canonical] ?? summaries[id];
    return summary is Map ? Map<String, dynamic>.from(summary) : {};
  }
}

class LocalPlaceRating extends StatelessWidget {
  final Map<String, dynamic> place;
  final ApiService? api;
  const LocalPlaceRating({super.key, required this.place, this.api});
  @override
  Widget build(BuildContext context) => ValueListenableBuilder<int>(
        valueListenable: LocalReviewRatings.revision,
        builder: (_, revision, child) => FutureBuilder<Map<String, dynamic>>(
          future: LocalReviewRatings.forPlace(DestinationUtils.resolveId(place),
              api: api),
          builder: (_, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) return const SizedBox.shrink();
            final data = snapshot.data ?? {};
            final demo = data['fypPreview'] == true;
            final rating = num.tryParse('${data['rating']}');
            final count = int.tryParse('${data['reviews']}') ?? 0;
            if (rating == null ||
                !rating.isFinite ||
                rating < 1 ||
                rating > 5 ||
                count < 1) {
              return const SizedBox.shrink();
            }
            return Semantics(
                label:
                    '${demo ? 'Private FYP' : 'TravelMate'} ${rating.toStringAsFixed(1)} out of 5, $count reviews',
                child: StatusChip(
                    text:
                        '${demo ? 'FYP · ' : ''}${rating.toStringAsFixed(1)} · $count ${count == 1 ? 'review' : 'reviews'}',
                    icon: Icons.star_rounded));
          },
        ),
      );
}
