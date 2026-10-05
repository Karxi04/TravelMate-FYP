import 'package:flutter/material.dart';

import '../theme/app_theme.dart';
import 'ink_card.dart';
import 'travel_widgets.dart';

class RecommendationCard extends StatelessWidget {
  final Map<String, dynamic> recommendation;
  final String source;
  final VoidCallback onView;
  final VoidCallback? onAddToTrip;

  const RecommendationCard({
    super.key,
    required this.recommendation,
    required this.onView,
    this.onAddToTrip,
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
    final raw = recommendation['finalScore'] ?? recommendation['score'];
    if (raw is num) return raw.clamp(0, 100);
    return num.tryParse((raw ?? '').toString())?.clamp(0, 100);
  }

  List<String> get _reasons {
    final rawReasons = recommendation['matchReasons'];
    if (rawReasons is List) {
      return rawReasons
          .map((value) => value.toString().trim())
          .where((value) => value.isNotEmpty)
          .take(2)
          .toList();
    }

    final raw = (recommendation['recommendationReason'] ??
            recommendation['reason'] ??
            '')
        .toString();
    if (raw.trim().isEmpty) return const [];
    return raw
        .split('•')
        .map((value) => value.trim())
        .where((value) =>
            value.isNotEmpty &&
            !RegExp(r'^\d+(\.\d+)?%\s*match$', caseSensitive: false)
                .hasMatch(value))
        .take(2)
        .toList();
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
    final rating = recommendation['rating'];

    return Semantics(
      container: true,
      label: score == null
          ? 'Recommended destination, $_title'
          : 'Recommended destination, $_title, ${score.round()} percent match',
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
                      if (score != null) ...[
                        const SizedBox(width: AppSpacing.xs),
                        StatusChip(
                          text: '${score.round()}% match',
                          icon: Icons.auto_awesome_rounded,
                        ),
                      ],
                    ],
                  ),
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
                  if (_category.isNotEmpty || rating != null) ...[
                    const SizedBox(height: AppSpacing.sm),
                    Wrap(
                      spacing: AppSpacing.xs,
                      runSpacing: AppSpacing.xs,
                      children: [
                        if (_category.isNotEmpty)
                          StatusChip(
                            text: _category,
                            tone: AppStatusTone.neutral,
                          ),
                        if (rating != null)
                          StatusChip(
                            text: '$rating rating',
                            icon: Icons.star_rounded,
                            tone: AppStatusTone.neutral,
                          ),
                      ],
                    ),
                  ],
                  if (reasons.isNotEmpty) ...[
                    const SizedBox(height: AppSpacing.sm),
                    ...reasons.map(
                      (reason) => Padding(
                        padding: const EdgeInsets.only(bottom: AppSpacing.xxs),
                        child: Row(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Padding(
                              padding: EdgeInsets.only(top: 2),
                              child: Icon(
                                Icons.check_circle_outline_rounded,
                                size: AppSizes.iconSmall,
                                color: AppColors.primary,
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
}
