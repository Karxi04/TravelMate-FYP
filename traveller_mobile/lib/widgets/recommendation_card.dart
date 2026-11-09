import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
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

  const RecommendationCard({
    super.key,
    required this.recommendation,
    required this.onView,
    this.onAddToTrip,
    this.preferenceFeedback,
    this.onPreferenceFeedback,
    this.feedbackBusy = false,
    this.source = '',
  });

  String get _title =>
      (recommendation['title'] ?? recommendation['name'] ?? 'Destination')
          .toString();

  String get _location => (recommendation['address'] ??
          recommendation['location'] ??
          recommendation['city'] ??
          recommendation['state'] ??
          '')
      .toString()
      .trim();

  String get _category =>
      (recommendation['category'] ?? recommendation['type'] ?? '')
          .toString()
          .trim();

  num? get _matchScore {
    final raw = _hasPersonalScore ? recommendation['personalSuitabilityScore'] : recommendation['finalScore'] ?? recommendation['score'];
    if (raw == null || raw == '') return null;
    final num? val = raw is num ? raw : num.tryParse(raw.toString());
    if (val == null || !val.isFinite) return null;
    return val.clamp(0, 100);
  }

  bool get _hasPersonalScore {
    final score = recommendation['personalSuitabilityScore'];
    return const ['relevance_v2','recovery_v3'].contains(recommendation['scoringVersion']) && score is num && score.isFinite && score >= 0 && score <= 100;
  }
  String get _scoreLabel => _hasPersonalScore ? 'Personal match' : 'Recommendation score';

  List<String> get _matchedInterests {
    final raw = recommendation['matchedInterests'];
    if (raw is List) {
      return raw
          .map((e) => e.toString().trim())
          .where((e) => e.isNotEmpty)
          .take(3)
          .toList();
    }
    return const [];
  }

  static bool _isScoreOrMatchToken(String value) {
    final lower = value.toLowerCase().trim();
    return RegExp(r'^\d+(\.\d+)?/100 hybrid ranking$').hasMatch(lower) || RegExp(r'^\d+(\.\d+)?%\s*match$').hasMatch(lower) ||
        RegExp(r'^(?:recommendation\s+)?score:?\s*\d+(\.\d+)?(\/100)?$')
            .hasMatch(lower);
  }

  List<String> get _reasons {
    final rawReasons = recommendation['matchReasons'];
    if (rawReasons is List) {
      final list = rawReasons
          .map((value) => value.toString().trim())
          .where((value) =>
              value.isNotEmpty &&
              !_isScoreOrMatchToken(value))
          .take(2)
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
          .map((value) => value.trim())
          .where((value) =>
              value.isNotEmpty &&
              !_isScoreOrMatchToken(value))
          .take(2)
          .toList();
      if (parts.isNotEmpty) return parts;
    }

    return const ['Recommended based on available destination information.'];
  }

  String get _source =>
      (recommendation['recommendationSource'] ?? source).toString().trim();

  String get _destinationKey => (recommendation['destinationId'] ??
          recommendation['place_id'] ??
          recommendation['id'] ??
          _title)
      .toString();

  bool get _showSourceDisclosure {
    final normalized = _source.toLowerCase();
    return normalized.isNotEmpty &&
        normalized != 'live' &&
        normalized != 'provider' &&
        normalized != 'live_provider' &&
        normalized != 'serpapi';
  }

  @override
  Widget build(BuildContext context) {
    final score = _matchScore;
    final reasons = _reasons;

    return Semantics(
      container: true,
      label: score == null
          ? 'Recommended destination, $_title'
          : 'Recommended destination, $_title, $_scoreLabel ${score.round()} out of 100',
      child: InkCard(
        padding: EdgeInsets.zero,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            TravelPlaceImage(
              place: recommendation,
              width: double.infinity,
              height: null,
              aspectRatio: AppSizes.destinationImageAspectRatio,
              borderRadius: const BorderRadius.vertical(
                top: Radius.circular(AppRadii.large),
              ),
            ),
            Padding(
              padding: AppSpacing.card,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(
                        child: Text(
                          _title,
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.titleLarge,
                        ),
                      ),
                      if (onPreferenceFeedback != null)
                        PopupMenuButton<String>(
                          key: ValueKey(
                            'recommendation-feedback-$_destinationKey',
                          ),
                          enabled: !feedbackBusy,
                          tooltip: 'Improve future recommendations',
                          icon: feedbackBusy
                              ? const SizedBox.square(
                                  dimension: 18,
                                  child: CircularProgressIndicator(
                                    strokeWidth: 2,
                                  ),
                                )
                              : const Icon(Icons.more_vert_rounded),
                          onSelected: onPreferenceFeedback,
                          itemBuilder: (context) => [
                            PopupMenuItem(
                              value: 'more_like_this',
                              child: ListTile(
                                contentPadding: EdgeInsets.zero,
                                leading: Icon(
                                  preferenceFeedback == 'more_like_this'
                                      ? Icons.check_circle_rounded
                                      : Icons.thumb_up_alt_outlined,
                                ),
                                title: const Text('More like this'),
                              ),
                            ),
                            PopupMenuItem(
                              value: 'not_for_me',
                              child: ListTile(
                                contentPadding: EdgeInsets.zero,
                                leading: Icon(
                                  preferenceFeedback == 'not_for_me'
                                      ? Icons.check_circle_rounded
                                      : Icons.thumb_down_alt_outlined,
                                ),
                                title: const Text('Not for me'),
                              ),
                            ),
                          ],
                        ),
                    ],
                  ),
                  if (preferenceFeedback != null) ...[
                    const SizedBox(height: AppSpacing.xs),
                    StatusChip(
                      text: preferenceFeedback == 'more_like_this'
                          ? 'More like this saved'
                          : 'Not for me saved',
                      icon: preferenceFeedback == 'more_like_this'
                          ? Icons.thumb_up_alt_outlined
                          : Icons.thumb_down_alt_outlined,
                      tone: AppStatusTone.neutral,
                    ),
                  ],
                  if (_location.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.location_on_outlined,
                          size: AppSizes.iconSmall,
                          color: AppColors.textSecondary,
                        ),
                        const SizedBox(width: AppSpacing.xxs),
                        Expanded(
                          child: Text(
                            _location,
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context)
                                .textTheme
                                .bodySmall
                                ?.copyWith(color: AppColors.textSecondary),
                          ),
                        ),
                      ],
                    ),
                  ],
                  const SizedBox(height: AppSpacing.sm),
                  Wrap(
                    spacing: AppSpacing.xs,
                    runSpacing: AppSpacing.xs,
                    children: [
                      if (score != null)
                        InkWell(
                          onTap: () => _showScoreExplanation(context, score),
                          borderRadius: BorderRadius.circular(AppRadii.pill),
                          child: Tooltip(
                            message:
                                '$_scoreLabel: ${score.round()}/100. Tap for details.',
                            child: StatusChip(
                              text: '$_scoreLabel: ${score.round()}/100',
                              icon: Icons.auto_awesome_rounded,
                            ),
                          ),
                        ),
                      if (_category.isNotEmpty)
                        StatusChip(
                          text: _category,
                          tone: AppStatusTone.neutral,
                        ),
                      LocalPlaceRating(place: recommendation),
                      for (final interest in _matchedInterests)
                        StatusChip(
                          text: interest,
                          icon: Icons.check_circle_outline_rounded,
                          tone: AppStatusTone.neutral,
                        ),
                    ],
                  ),
                  if (const ['relevance_v2','recovery_v3'].contains(recommendation['scoringVersion']) && !_hasPersonalScore)
                    Text('Personal match unavailable — interest evidence missing.',style:Theme.of(context).textTheme.bodySmall),
                  if (_hasPersonalScore) ...[
                    const SizedBox(height: AppSpacing.xxs),
                    Text('Hybrid ranking: ${((recommendation['hybridRankingScore'] ?? recommendation['finalScore']) as num?)?.toStringAsFixed(1) ?? '-'} /100',style:Theme.of(context).textTheme.bodySmall),
                    if ((recommendation['evidenceConfidence'] as num? ?? 0) < 1)
                      Text('Limited profile metadata (${((recommendation['evidenceConfidence'] as num? ?? 0)*100).round()}% of requested evidence available)',style:Theme.of(context).textTheme.bodySmall),
                    if ((recommendation['collaborativeConfidence'] as num? ?? 0) == 0)
                      Text('No similar-traveller ratings yet',style:Theme.of(context).textTheme.bodySmall),
                  ],
                  if (reasons.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    ...reasons.map(
                      (reason) => Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Padding(
                              padding: const EdgeInsets.only(top: 2),
                              child: Icon(
                                reason ==
                                        'Recommended based on available destination information.'
                                    ? Icons.info_outline_rounded
                                    : Icons.check_circle_outline_rounded,
                                size: AppSizes.iconSmall,
                                color: reason ==
                                        'Recommended based on available destination information.'
                                    ? AppColors.textSecondary
                                    : AppColors.primary,
                              ),
                            ),
                            const SizedBox(width: AppSpacing.xs),
                            Expanded(
                              child: Text(
                                reason,
                                maxLines: 2,
                                overflow: TextOverflow.ellipsis,
                                style: Theme.of(context).textTheme.bodyMedium,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                  if (_showSourceDisclosure) ...[
                    const SizedBox(height: AppSpacing.xs),
                    SourceFallbackBadge(source: _source),
                  ],
                  const SizedBox(height: AppSpacing.md),
                  Row(
                    children: [
                      Expanded(
                        child: SecondaryButton(
                          key: ValueKey('recommendation-view-$_destinationKey'),
                          label: 'View',
                          onPressed: onView,
                        ),
                      ),
                      if (onAddToTrip != null) ...[
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: PrimaryButton(
                            key: ValueKey(
                              'recommendation-add-$_destinationKey',
                            ),
                            label: 'Add to trip',
                            onPressed: onAddToTrip,
                          ),
                        ),
                      ],
                    ],
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
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
    final collaborativeSource =
        (recommendation['collaborativeSource'] ?? '').toString().toLowerCase();
    final isColdStart = collaborativeConfidence <= 0 ||
        collaborativeRatingCount == 0 ||
        collaborativeSource.contains('no similar traveller') ||
        collaborativeSource.contains('neutral') ||
        (breakdown != null &&
            (breakdown['collaborative'] as num?)?.round() == 50 &&
            collaborativeRatingCount == 0);

    showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            0,
            AppSpacing.md,
            AppSpacing.lg,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Icon(
                    Icons.auto_awesome_rounded,
                    color: AppColors.primary,
                  ),
                  const SizedBox(width: AppSpacing.xs),
                  Expanded(
                    child: Text(
                      '${_hasPersonalScore ? 'Personal match' : 'Recommendation Score'} (${score.round()}/100)',
                      style: Theme.of(sheetContext).textTheme.titleLarge,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                'A 0–100 hybrid ranking score used to order recommendations for your profile. This is not an enjoyment probability or percentage guarantee.',
                style: Theme.of(sheetContext).textTheme.bodySmall?.copyWith(
                      color: AppColors.textSecondary,
                    ),
              ),
              const SizedBox(height: AppSpacing.md),
              if (_hasPersonalScore) ...[
                Text('Personal match averages only supported profile signals. Evidence coverage describes available metadata, not prediction accuracy. Hybrid ranking retains 60% content, 30% similar travellers and 10% popularity.'),
                const SizedBox(height: AppSpacing.sm),
                Text('Hybrid ranking: ${recommendation['hybridRankingScore']} /100'),
              ],
              if (breakdown != null) ...[
                _breakdownCard(
                  sheetContext,
                  title: 'Travel style & interests (60% weight)',
                  scoreText:
                      '${(breakdown['content'] as num?)?.round() ?? '-'}/100',
                  description:
                      'Evaluates compatibility with your saved travel interests, budget preference, and travel pace.',
                ),
                const SizedBox(height: AppSpacing.sm),
                _breakdownCard(
                  sheetContext,
                  title: 'Similar traveller evidence (30% weight)',
                  scoreText: isColdStart
                      ? '50/100 (Neutral baseline)'
                      : '${(breakdown['collaborative'] as num?)?.round() ?? '-'}/100',
                  description: isColdStart
                      ? 'No peer ratings from similar travellers are recorded yet. A neutral 50/100 ranking prior is used. Personal match is assessed separately.'
                      : 'Based on feedback and ratings from travellers with similar travel styles.',
                ),
                const SizedBox(height: AppSpacing.sm),
                _breakdownCard(
                  sheetContext,
                  title: 'Destination popularity (10% weight)',
                  scoreText:
                      '${(breakdown['popularity'] as num?)?.round() ?? '-'}/100',
                  description: '${recommendation['popularitySource']}'.startsWith('neutral_')
                      ? 'Verified provider popularity evidence is unavailable. A neutral 50/100 baseline is used; no business rating is invented.'
                      : 'Based on public ratings and review coverage across all visitors.',
                ),
              ] else ...[
                Container(
                  padding: AppSpacing.card,
                  decoration: BoxDecoration(
                    color: AppColors.surfaceElevated,
                    borderRadius: AppRadii.control,
                    border: Border.all(color: AppColors.divider),
                  ),
                  child: Row(
                    children: [
                      const Icon(
                        Icons.info_outline_rounded,
                        color: AppColors.textSecondary,
                      ),
                      const SizedBox(width: AppSpacing.sm),
                      Expanded(
                        child: Text(
                          'Detailed score breakdown is not available for this recommendation.',
                          style: Theme.of(sheetContext).textTheme.bodySmall,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              const SizedBox(height: AppSpacing.md),
              SizedBox(
                width: double.infinity,
                child: SecondaryButton(
                  label: 'Close',
                  onPressed: () => Navigator.pop(sheetContext),
                ),
              ),
            ],
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
      padding: AppSpacing.card,
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated,
        borderRadius: AppRadii.control,
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  title,
                  style: Theme.of(context).textTheme.titleSmall,
                ),
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
