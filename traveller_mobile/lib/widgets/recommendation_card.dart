import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../theme/app_theme.dart';
import '../core/utils/recommendation_page.dart';
import 'ink_card.dart';
import 'travel_widgets.dart';
import 'local_place_rating.dart';

class RecommendationCard extends StatelessWidget {
  final Map<String, dynamic> recommendation;
  final String source;
  final VoidCallback onView;
  final VoidCallback? onAddToTrip;
  final String? preferenceFeedback;
  final ValueChanged<String>? onPreferenceFeedback;
  final bool feedbackBusy;
  final bool discovery;
  final bool carousel;
  final VoidCallback? onRefreshEvidence;

  const RecommendationCard({
    super.key,
    required this.recommendation,
    required this.onView,
    this.onAddToTrip,
    this.preferenceFeedback,
    this.onPreferenceFeedback,
    this.feedbackBusy = false,
    this.discovery = false,
    this.carousel = false,
    this.onRefreshEvidence,
    this.source = '',
  });

  String get _title =>
      (recommendation['title'] ?? recommendation['name'] ?? 'Destination')
          .toString();

  bool get _demonstration => recommendation['recommendationEvidenceMode'] == 'demonstration' && recommendation['synthetic'] == true;
  bool get _evaluation => recommendation['recommendationEvidenceMode'] == 'fyp_evaluation' && recommendation['synthetic'] == true;
  bool get _sampleEvidence => _demonstration || _evaluation;
  VoidCallback? get _addToTrip => _demonstration ? null : onAddToTrip;
  Widget get _reviewRating => _evaluation ? _evaluationRating : _demonstration
      ? LocalReviewRatingBadge(summary: Map<String, dynamic>.from(recommendation['demonstrationReviewSummary'] as Map? ?? {}), maxLines: null)
      : LocalPlaceRating(place: recommendation, maxLines: null);

  Map? get _localEvaluationSummary {
    final local = recommendation['demonstrationReviewSummary'];
    final localRating = local is Map ? num.tryParse('${local['rating']}') : null;
    final localCount = local is Map ? num.tryParse('${local['reviews']}') : null;
    if (local is! Map || local['source'] != 'demonstration_approved_reviews' || local['synthetic'] != true ||
        localRating == null || !localRating.isFinite || localRating < 1 || localRating > 5 ||
        localCount == null || !localCount.isFinite || localCount <= 0 || localCount != localCount.roundToDouble()) return null;
    return {'source':local['source'],'rating':localRating,'reviewCount':localCount.toInt()};
  }

  Widget get _evaluationRating {
    final popularity = recommendation['popularityEvidence'];
    final evidence = _localEvaluationSummary ??
        (popularity is Map && popularity['source']=='demonstration_approved_reviews' ? popularity : null);
    if (evidence == null) return const StatusChip(text: 'Not rated yet', maxLines: null);
    final rating = num.tryParse('${evidence['rating']}');
    if (rating == null || !rating.isFinite || rating < 1 || rating > 5 ||
        evidence['source']!='demonstration_approved_reviews') {
      return const StatusChip(text: 'Not rated yet', maxLines: null);
    }
    final count = evidence['reviewCount'];
    return LocalReviewRatingBadge(summary:{'rating':rating,'reviews':count,
      'recommendationEvidenceMode':'fyp_evaluation','ratingBasis':'private_illustrative',
      'reviewEnvironment':'private_demo','privateExamplesAllowed':true}, maxLines:null);
  }

  String get _location => (recommendation['address'] ??
          recommendation['location'] ??
          recommendation['city'] ??
          recommendation['state'] ??
          '')
      .toString()
      .trim();

  String get _category {
    final evidence = recommendation['verifiedDestinationEvidence'];
    if (evidence is Map && evidence['suppliesCategory'] == true) {
      return '${evidence['category'] ?? ''}'.trim();
    }
    return (recommendation['category'] ?? recommendation['type'] ?? '')
        .toString()
        .trim();
  }

  num? get _matchScore {
    final raw = _hasPersonalScore
        ? recommendation['personalSuitabilityScore']
        : recommendation['finalScore'] ?? recommendation['score'];
    if (raw == null || raw == '') return null;
    final num? val = raw is num ? raw : num.tryParse(raw.toString());
    if (val == null || !val.isFinite) return null;
    return val.clamp(0, 100);
  }

  bool get _hasPersonalScore {
    final score = recommendation['personalSuitabilityScore'];
    return const ['relevance_v2', 'recovery_v3']
            .contains(recommendation['scoringVersion']) &&
        score is num &&
        score.isFinite &&
        score >= 0 &&
        score <= 100;
  }

  String get _scoreLabel =>
      _hasPersonalScore ? 'Personal match' : 'Recommendation score';

  List<String> get _matchedInterests {
    final raw = recommendation['matchedInterests'];
    if (raw is List) {
      return raw
          .map((e) => e.toString().trim())
          .where((e) => e.isNotEmpty)
          .toList();
    }
    return const [];
  }

  static bool _isScoreOrMatchToken(String value) {
    final lower = value.toLowerCase().trim();
    return RegExp(r'^\d+(\.\d+)?/100 hybrid ranking$').hasMatch(lower) ||
        RegExp(r'^\d+(\.\d+)?%\s*match$').hasMatch(lower) ||
        RegExp(r'^(?:recommendation\s+)?score:?\s*\d+(\.\d+)?(\/100)?$')
            .hasMatch(lower);
  }

  List<String> get _reasons {
    final rawReasons = recommendation['matchReasons'];
    if (rawReasons is List) {
      final list = rawReasons
          .map((value) => _naturalReason(value.toString().trim()))
          .where((value) => value.isNotEmpty && !_isScoreOrMatchToken(value))
          .toList();
      if (list.isNotEmpty) return list;
    }

    final raw = (recommendation['recommendationReason'] ??
            recommendation['reason'] ??
            '')
        .toString();
    if (raw.trim().isNotEmpty) {
      final parts = raw
          .split('•')
          .map((value) => _naturalReason(value.trim()))
          .where((value) => value.isNotEmpty && !_isScoreOrMatchToken(value))
          .toList();
      if (parts.isNotEmpty) return parts;
    }

    return const ['Recommended based on available destination information.'];
  }

  String _naturalReason(String value) => _sampleEvidence ? value
      .replaceAll('Highly rated in sample community data','Popular among reviewers')
      .replaceAll('Popular in sample community data','Popular among reviewers') : value;

  String get _source =>
      (recommendation['recommendationSource'] ?? source).toString().trim();

  String get _destinationKey => (recommendation['destinationId'] ??
          recommendation['place_id'] ??
          recommendation['id'] ??
          _title)
      .toString();

  bool get _showSourceDisclosure {
    final normalized = _source.toLowerCase();
    return !_sampleEvidence && normalized.isNotEmpty &&
        normalized != 'live' &&
        normalized != 'provider' &&
        normalized != 'live_provider' &&
        normalized != 'serpapi';
  }

  PopupMenuButton<String> _feedbackMenu() => PopupMenuButton<String>(
        key: ValueKey('recommendation-feedback-$_destinationKey'),
        enabled: !feedbackBusy,
        tooltip: 'Improve future recommendations',
        icon: feedbackBusy
            ? const SizedBox.square(
                dimension: 18, child: CircularProgressIndicator(strokeWidth: 2))
            : const Icon(Icons.more_vert_rounded),
        onSelected: onPreferenceFeedback,
        itemBuilder: (context) => [
          PopupMenuItem(
              value: 'more_like_this',
              child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(preferenceFeedback == 'more_like_this'
                      ? Icons.check_circle_rounded
                      : Icons.thumb_up_alt_outlined),
                  title: const Text('More like this'))),
          PopupMenuItem(
              value: 'not_for_me',
              child: ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(preferenceFeedback == 'not_for_me'
                      ? Icons.check_circle_rounded
                      : Icons.thumb_down_alt_outlined),
                  title: const Text('Not for me'))),
        ],
      );

  @override
  Widget build(BuildContext context) {
    final score = _matchScore;
    final theme = Theme.of(context).textTheme;
    final detail = Padding(
      padding: AppSpacing.card,
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Text(_title, style: theme.titleLarge),
        if (_location.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(_location, style: theme.bodySmall?.copyWith(color: AppColors.textSecondary)),
        ],
        const SizedBox(height: AppSpacing.sm),
        Wrap(
          key: ValueKey('recommendation-labels-$_destinationKey'),
          spacing: AppSpacing.xs, runSpacing: AppSpacing.xs,
          children: [
            if (score != null) InkWell(
              onTap: () => _showScoreExplanation(context, score),
              borderRadius: BorderRadius.circular(AppRadii.pill),
              child: StatusChip(maxLines: null,
                text: discovery ? 'Why this suggestion' : '$_scoreLabel: ${score.round()}/100',
                icon: Icons.auto_awesome_rounded)),
            if (_evaluation && recommendation['finalScore'] is num)
              StatusChip(text: 'Hybrid score: ${(recommendation['finalScore'] as num).toStringAsFixed(1)}/100', maxLines: null),
            if (_category.isNotEmpty) StatusChip(text: _category, maxLines: null, tone: AppStatusTone.neutral),
            for (final interest in _matchedInterests) StatusChip(text: interest, maxLines: null,
              icon: Icons.check_circle_outline_rounded, tone: AppStatusTone.neutral),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        Row(key: ValueKey('recommendation-metadata-$_destinationKey'),
          crossAxisAlignment: CrossAxisAlignment.start, children: [
            Expanded(child: Wrap(spacing: AppSpacing.xs, runSpacing: AppSpacing.xs, children: [
              _reviewRating,
              if (_showSourceDisclosure) SourceFallbackBadge(source: _source, maxLines: null),
            ])),
            if (onPreferenceFeedback != null && !_demonstration) _feedbackMenu(),
          ]),
        if (preferenceFeedback != null && !_demonstration) ...[
          const SizedBox(height: AppSpacing.xs),
          StatusChip(maxLines: null, text: preferenceFeedback == 'more_like_this'
              ? 'More like this saved' : 'Not for me saved', tone: AppStatusTone.neutral),
        ],
        if (recommendation['nearbyDistanceKm'] is num) ...[
          const SizedBox(height: AppSpacing.xs),
          Text('Nearby · ${recommendation['city'] ?? 'Locality not supplied'} · '
              '${(recommendation['nearbyDistanceKm'] as num).toStringAsFixed(1)} km straight-line'),
        ],
        if (!discovery && const ['relevance_v2', 'recovery_v3'].contains(recommendation['scoringVersion']) && !_hasPersonalScore)
          const Padding(padding: EdgeInsets.only(top: AppSpacing.xs),
            child: Text('Personal match unavailable — interest evidence missing.')),
        if (!discovery && _hasPersonalScore) ...[
          const SizedBox(height: AppSpacing.xs),
          Text('Hybrid ranking: ${((recommendation['hybridRankingScore'] ?? recommendation['finalScore']) as num?)?.toStringAsFixed(1) ?? '-'} /100', style: theme.bodySmall),
          if ((recommendation['evidenceConfidence'] as num? ?? 0) < 1)
            Text('Limited profile metadata (${((recommendation['evidenceConfidence'] as num? ?? 0) * 100).round()}% of requested evidence available)', style: theme.bodySmall),
          if (recommendation['collaborativeConfidence'] == 0)
            Text('No qualifying similar-traveller ratings in this result', style: theme.bodySmall),
        ],
        if (discovery && recommendation['foodExperienceType'] != null) ...[
          const SizedBox(height: AppSpacing.xs),
          Text(switch (recommendation['foodExperienceType']) {
            'dining' => 'Food stop / dining',
            'food_museum' => 'Food-themed museum; dining is not implied.',
            'cooking' => 'Cooking experience; check booking details.',
            'culinary_culture' => 'Spices and culinary culture; a cooking class is not implied.',
            _ => 'Food-related experience; dining is not confirmed.',
          }, style: theme.bodySmall),
        ],
        const SizedBox(height: AppSpacing.sm),
        for (final reason in _reasons) Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
          child: Text(reason, style: theme.bodyMedium)),
        if (carousel) const Spacer(),
        const SizedBox(height: AppSpacing.md),
        SecondaryButton(key: ValueKey('recommendation-view-$_destinationKey'),
          label: _demonstration ? 'View simulation' : 'View', onPressed: onView),
        if (_addToTrip != null) ...[
          const SizedBox(height: AppSpacing.xs),
          PrimaryButton(key: ValueKey('recommendation-add-$_destinationKey'),
            label: 'Add to trip', onPressed: _addToTrip),
        ],
      ]),
    );
    final card = Semantics(container: true, label: score == null ? 'Recommended destination, $_title'
        : 'Recommended destination, $_title, $_scoreLabel ${score.round()} out of 100',
      child: InkCard(padding: EdgeInsets.zero, child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          TravelPlaceImage(key: ValueKey('recommendation-image-$_destinationKey'),
            place: recommendation, width: double.infinity, height: null,
            aspectRatio: AppSizes.destinationImageAspectRatio,
            borderRadius: const BorderRadius.vertical(top: Radius.circular(AppRadii.large))),
          if (carousel) Expanded(child: detail) else detail,
        ])));
    // At most four Home cards share their actual intrinsic height, including all wrapped rows.
    return carousel ? IntrinsicHeight(key: ValueKey('recommendation-carousel-$_destinationKey'), child: card) : card;
  }

  void _showScoreExplanation(BuildContext context, num score) {
    final breakdown = recommendation['scoreBreakdown'] is Map
        ? Map<String, dynamic>.from(recommendation['scoreBreakdown'] as Map)
        : null;
    final collaborativeConfidence = num.tryParse(
            (recommendation['collaborativeConfidence'] ?? '').toString()) ??
        0;
    final collaborativeRatingCount = int.tryParse(
            (recommendation['collaborativeRatingCount'] ?? '').toString()) ??
        0;
    final hasPeerEvidence = collaborativeConfidence > 0 && collaborativeRatingCount > 0;
    final hasEvidenceDetails = recommendation['collaborativeConfidence'] != null ||
        recommendation['collaborativeRatingCount'] != null;
    final isColdStart = !hasPeerEvidence && hasEvidenceDetails;
    final rawPeerScore = num.tryParse('${recommendation['rawCollaborativeScore']}');
    final popularityEvidence = recommendation['popularityEvidence'] is Map
        ? Map<String, dynamic>.from(recommendation['popularityEvidence'] as Map) : null;
    final popularityRating = num.tryParse('${popularityEvidence?['rating']}');
    final popularityCount = popularityEvidence?['reviewCount'];
    final popularitySource = popularityEvidence?['source'];
    final popularityDescription = popularityEvidence == null
        ? 'This saved recommendation uses an older evidence format. Detailed popularity provenance is unavailable in this format. Regenerate recommendations to evaluate current evidence.'
        : popularitySource == 'provider_rating_review_count'
            ? '${_evaluation ? 'This saved evaluation predates the local-only policy. Regenerate to use current local evidence; provider popularity is no longer used in this evaluation. ' : ''}Verified provider rating: ${popularityRating?.toStringAsFixed(1)}/5. ${popularityCount == null ? 'Provider review count unavailable.' : '$popularityCount provider reviews.'}'
        : popularitySource == 'genuine_approved_local_reviews'
            ? 'Approved genuine TravelMate reviews: ${popularityRating?.toStringAsFixed(1)}/5 from $popularityCount reviews loaded for this generation. Demonstration reviews are excluded.'
        : popularitySource == 'demonstration_approved_reviews'
            ? 'Sample community data: local approved evaluation review rating ${popularityRating?.toStringAsFixed(1)}/5 from $popularityCount reviews. This is the unweighted destination aggregate, without reviewer-similarity weighting. These are evaluation contributions, not verified real tourist submissions.'
        : _sampleEvidence
            ? 'No eligible rating evidence was available for this evaluation. A neutral 50/100 baseline is used.'
            : 'No verified provider rating or approved genuine local review evidence was available. A neutral 50/100 baseline is used. Demonstration reviews do not affect this score.';
    final fallbackDetail = const {
      'missing_current_preferences': 'Your preference profile was unavailable for this generation.',
      'missing_peer_preferences': 'Reviewers had no matching saved preference profiles.',
      'no_similar_peers': 'Available reviewer profiles were below the similarity threshold.',
      'missing_or_dissimilar_peer_profiles': 'Reviewer preferences were missing or below the similarity threshold.',
    }[recommendation['collaborativeFallbackReason']];
    final collaborativeDescription = !hasEvidenceDetails
        ? 'This saved recommendation has no peer-evidence details. Refresh recommendations to evaluate current feedback; the saved score has not been recalculated.'
        : isColdStart
            ? '${_sampleEvidence ? 'No evaluation contributor ratings' : 'No peer ratings from similar travellers'} qualified in this generation. Eligible reviewers: 0. Evidence confidence: 0%. A neutral 50/100 ranking prior is used, not an average review rating. Personal match is assessed separately.${fallbackDetail == null ? '' : ' $fallbackDetail'}'
            : '${_sampleEvidence ? 'Qualifying evaluation contributors' : 'Eligible reviewers'}: $collaborativeRatingCount. ${_sampleEvidence ? 'Sample p' : 'P'}eer ratings are similarity-weighted. '
              '${rawPeerScore == null ? '' : 'Raw peer score: ${rawPeerScore.toStringAsFixed(1)}/100. '}'
              'Evidence confidence: ${(collaborativeConfidence * 100).round()}%. '
              'Sparse evidence is blended toward 50; confidence is not prediction accuracy. '
              'A result of 50 can be evidence-backed and is not automatically a cold start.';

    String valueText(Object? value) {
      final number = num.tryParse('$value');
      if (number == null || !number.isFinite || number < 0 || number > 100) return 'Unavailable';
      return '${number.toStringAsFixed(number == number.roundToDouble() ? 0 : 1)}/100';
    }
    final overall = recommendation['hybridRankingScore'] ?? recommendation['finalScore'] ?? recommendation['score'];
    final peerSummary = !hasEvidenceDetails
        ? 'Peer-rating details are unavailable for this saved result.'
        : isColdStart
            ? 'Not enough similar reviewer ratings yet.'
            : _sampleEvidence
                ? 'Based on illustrative reviewer profiles with similar interests.'
                : 'Based on ratings from reviewer profiles with similar interests.';
    final ratingSummary = switch (popularitySource) {
      'demonstration_approved_reviews' => 'Based on approved illustrative community review ratings.',
      'genuine_approved_local_reviews' => 'Based on approved TravelMate review ratings.',
      'provider_rating_review_count' => 'Based on provider review ratings.',
      _ => popularityEvidence == null
          ? 'Rating-source details are unavailable for this saved result.'
          : 'Not enough qualifying review information yet.',
    };
    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(maxHeight: MediaQuery.sizeOf(sheetContext).height * .88),
          child: SingleChildScrollView(
            key: const ValueKey('recommendation-explanation-scroll'),
            padding: const EdgeInsets.fromLTRB(AppSpacing.md, 0, AppSpacing.md, AppSpacing.lg),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                Text('Why this suggestion?', style: Theme.of(sheetContext).textTheme.titleLarge),
                const SizedBox(height: AppSpacing.xs),
                Text(_matchedInterests.isNotEmpty
                    ? 'Matches your interests in ${_matchedInterests.join(', ')}.'
                    : 'Selected using available preference and destination information.'),
                const SizedBox(height: AppSpacing.sm),
                Text('Overall match: ${valueText(overall)}',
                    key: const ValueKey('overall-recommendation-score'),
                    style: Theme.of(sheetContext).textTheme.titleMedium),
                const SizedBox(height: AppSpacing.sm),
                if (breakdown != null) ...[
                  _breakdownCard(sheetContext,
                      title: 'Your interests (60%)',
                      scoreText: valueText(breakdown['content']),
                      description: 'Matches your travel style, interests and pace.'),
                  const SizedBox(height: AppSpacing.xs),
                  _breakdownCard(sheetContext,
                      title: 'Similar profiles (30%)',
                      scoreText: valueText(breakdown['collaborative']),
                      description: peerSummary),
                  const SizedBox(height: AppSpacing.xs),
                  _breakdownCard(sheetContext,
                      title: 'Popularity (10%)',
                      scoreText: valueText(breakdown['popularity']),
                      description: ratingSummary),
                ] else
                  const Text('Detailed score breakdown is not available for this saved recommendation.'),
                if (!recommendationHasCurrentEvidence(recommendation)) ...[
                  const SizedBox(height: AppSpacing.sm),
                  const Text(recommendationEvidenceUpdateMessage),
                  if (onRefreshEvidence != null) TextButton.icon(
                      key: const ValueKey('regenerate-recommendation-evidence'),
                      onPressed: () { Navigator.pop(sheetContext); onRefreshEvidence!(); },
                      icon: const Icon(Icons.refresh_rounded), label: const Text('Regenerate recommendations')),
                ],
                if (_sampleEvidence) ...[
                  const SizedBox(height: AppSpacing.sm),
                  const Text('Review information includes illustrative community evaluation data, not genuine customer peer evidence.'),
                ],
                ExpansionTile(
                  key: const PageStorageKey('recommendation-source-details'),
                  title: const Text('How recommendations work'),
                  childrenPadding: const EdgeInsets.only(bottom: AppSpacing.sm),
                  expandedCrossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    const Text('The overall score uses 60% interests, 30% similar profiles and 10% popularity. It is a ranking score, not an enjoyment probability.'),
                    if (_hasPersonalScore) ...[
                      const SizedBox(height: AppSpacing.sm),
                      const Text('Personal match averages only supported profile signals. Evidence coverage describes available metadata, not prediction accuracy.'),
                    ],
                    const SizedBox(height: AppSpacing.sm),
                    Text(collaborativeDescription),
                    const SizedBox(height: AppSpacing.sm),
                    Text(popularityDescription),
                    if (_sampleEvidence) ...[
                      const SizedBox(height: AppSpacing.sm),
                      const Text('Illustrative review contributions and simulated preference profiles are not verified genuine Traveller submissions. They remain separate from genuine recommendations.'),
                    ],
                    RecommendationDataSources(evaluation: _sampleEvidence, label: 'Review sources and attribution'),
                  ],
                ),
                const SizedBox(height: AppSpacing.sm),
                SecondaryButton(label: 'Close', onPressed: () => Navigator.pop(sheetContext)),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _breakdownCard(
    BuildContext context, {
    required String title,
    required String scoreText,
    required String description,
  }) {
    return Container(
      key: ValueKey('recommendation-score-$title'),
      padding: AppSpacing.card,
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated,
        borderRadius: AppRadii.control,
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: AppSpacing.sm,
            runSpacing: AppSpacing.xxs,
            crossAxisAlignment: WrapCrossAlignment.center,
            children: [
              Text(
                title,
                style: Theme.of(context).textTheme.titleSmall,
              ),
              StatusChip(
                text: scoreText,
                tone: AppStatusTone.neutral,
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            description,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ],
      ),
    );
  }
}


class RecommendationEvidenceNotice extends StatelessWidget {
  final VoidCallback? onRegenerate;
  final String message;
  const RecommendationEvidenceNotice({super.key, this.onRegenerate, this.message = recommendationEvidenceUpdateMessage});
  @override
  Widget build(BuildContext context) => InkCard(child: Column(
    crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(message),
      TextButton.icon(key: const ValueKey('update-recommendation-evidence'),
        onPressed: onRegenerate, icon: const Icon(Icons.refresh_rounded),
        label: const Text('Regenerate recommendations')),
    ]));
}

class RecommendationDataSources extends StatelessWidget {
  final bool evaluation;
  final String label;
  const RecommendationDataSources({super.key, required this.evaluation,this.label='Recommendation data sources'});
  @override
  Widget build(BuildContext context) => Align(alignment: Alignment.centerLeft,
    child: TextButton.icon(icon: const Icon(Icons.info_outline_rounded, size: 18),
      label: Text(label), onPressed: () => showModalBottomSheet<void>(
        context: context, showDragHandle: true, builder: (context) => SafeArea(child: SingleChildScrollView(
          padding: AppSpacing.page, child: Column(mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(evaluation ? 'Illustrative community information' : 'Genuine community configuration',
                style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: AppSpacing.sm),
              Text(evaluation
                ? 'Your saved preferences drive the same 60% content, 30% similar-traveller and 10% popularity calculation. Evaluation mode uses approved TravelMate sample community reviews only. Similarity-weighted peer ratings and the unweighted popularity aggregate remain separate. Missing local evidence uses a neutral ranking prior and Not rated yet. Provider ratings are excluded. Sample contributors are not verified real tourists. Evaluation results remain in owner-scoped server memory for one hour or restart. Your questionnaire and genuine history are unchanged. Trip actions use normal confirmations.'
                : 'Recommendations use your saved preferences, qualifying independent genuine reviews and verified provider ratings or approved genuine local ratings. Sample community reviews do not contribute. Missing peer evidence uses a confidence-aware neutral score.'),
              const SizedBox(height:AppSpacing.md),
              const Text('Data attribution'),
              TextButton(onPressed:()=>launchUrl(Uri.parse('https://www.geonames.org/'),mode:LaunchMode.externalApplication),
                child:const Text('GeoNames · CC BY 4.0')),
              TextButton(onPressed:()=>launchUrl(Uri.parse('https://open-meteo.com/en/docs/geocoding-api'),mode:LaunchMode.externalApplication),
                child:const Text('Location lookup by Open-Meteo · CC BY-NC 4.0')),
            ]))))));
}
