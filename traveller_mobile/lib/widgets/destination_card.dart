import 'package:flutter/material.dart';

import '../core/utils/destination_utils.dart';
import '../theme/app_theme.dart';
import 'ink_card.dart';
import 'travel_widgets.dart';

class DestinationCard extends StatelessWidget {
  final Map<String, dynamic> destination;
  final VoidCallback onView;
  final VoidCallback? onAddToTrip;
  final VoidCallback? onSave;
  final bool saved;
  final String source;
  final bool compact;

  const DestinationCard({
    super.key,
    required this.destination,
    required this.onView,
    this.onAddToTrip,
    this.onSave,
    this.saved = false,
    this.source = '',
    this.compact = false,
  });

  String get _id => DestinationUtils.resolveId(destination);
  String get _title => DestinationUtils.resolveName(destination);
  String get _location => (destination['address'] ??
          destination['location'] ??
          destination['city'] ??
          '')
      .toString()
      .trim();
  String get _category =>
      (destination['category'] ?? destination['type'] ?? '').toString().trim();
  String get _reason => (destination['searchReason'] ?? '').toString().trim();

  num? get _rating {
    final raw = destination['rating'];
    if (raw is num && raw > 0) return raw;
    final value = num.tryParse((raw ?? '').toString());
    return value != null && value > 0 ? value : null;
  }

  String get _resolvedSource =>
      (destination['source'] ?? source).toString().trim().toLowerCase();

  bool get _showSource => const {
        'cache',
        'cached',
        'fallback',
        'local',
        'demo',
      }.contains(_resolvedSource);

  Widget _metadata(BuildContext context) => Wrap(
        spacing: AppSpacing.xs,
        runSpacing: AppSpacing.xs,
        children: [
          if (_category.isNotEmpty)
            StatusChip(text: _category, tone: AppStatusTone.neutral),
          if (_rating != null)
            Semantics(
              label: '${_rating!} out of 5 stars',
              child: StatusChip(
                text: '${_rating!}',
                icon: Icons.star_rounded,
                tone: AppStatusTone.neutral,
              ),
            ),
        ],
      );

  Widget _details(BuildContext context, {required bool condensed}) => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            _title,
            maxLines: 2,
            overflow: TextOverflow.ellipsis,
            style: Theme.of(context).textTheme.titleLarge,
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
                    maxLines: condensed ? 1 : 2,
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
          const SizedBox(height: AppSpacing.xs),
          _metadata(context),
          if (!condensed && _reason.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            Text(
              _reason,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.textSecondary),
            ),
          ],
          if (_showSource) ...[
            const SizedBox(height: AppSpacing.xs),
            SourceFallbackBadge(source: _resolvedSource),
          ],
        ],
      );

  Widget _actions() => Row(
        children: [
          Expanded(
            child: SecondaryButton(
              key: ValueKey('destination-view-$_id'),
              label: 'View',
              onPressed: onView,
            ),
          ),
          if (onAddToTrip != null) ...[
            const SizedBox(width: AppSpacing.xs),
            Expanded(
              child: PrimaryButton(
                key: ValueKey('destination-add-$_id'),
                label: 'Add to trip',
                onPressed: onAddToTrip,
              ),
            ),
          ],
        ],
      );

  @override
  Widget build(BuildContext context) {
    return Semantics(
      container: true,
      label: _rating == null
          ? 'Destination, $_title'
          : 'Destination, $_title, ${_rating!} out of 5 stars',
      child: InkCard(
        padding: EdgeInsets.zero,
        child: compact
            ? Padding(
                padding: AppSpacing.card,
                child: Column(
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        TravelPlaceImage(
                          place: destination,
                          width: 104,
                          height: 104,
                          borderRadius: AppRadii.control,
                        ),
                        const SizedBox(width: AppSpacing.sm),
                        Expanded(child: _details(context, condensed: true)),
                      ],
                    ),
                    const SizedBox(height: AppSpacing.sm),
                    _actions(),
                  ],
                ),
              )
            : Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Stack(
                    children: [
                      InkWell(
                        onTap: onView,
                        borderRadius: const BorderRadius.vertical(
                          top: Radius.circular(AppRadii.large),
                        ),
                        child: TravelPlaceImage(
                          place: destination,
                          width: double.infinity,
                          height: null,
                          aspectRatio: AppSizes.destinationImageAspectRatio,
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(AppRadii.large),
                          ),
                        ),
                      ),
                      if (onSave != null)
                        Positioned(
                          top: AppSpacing.xs,
                          right: AppSpacing.xs,
                          child: Semantics(
                            button: true,
                            toggled: saved,
                            label: saved
                                ? 'Destination saved'
                                : 'Save destination',
                            child: Material(
                              color: AppColors.surface.withValues(alpha: .94),
                              shape: const CircleBorder(),
                              child: IconButton(
                                key: ValueKey('destination-save-$_id'),
                                tooltip: saved ? 'Saved' : 'Save destination',
                                onPressed: saved ? null : onSave,
                                icon: Icon(
                                  saved
                                      ? Icons.favorite_rounded
                                      : Icons.favorite_border_rounded,
                                ),
                              ),
                            ),
                          ),
                        ),
                    ],
                  ),
                  Padding(
                    padding: AppSpacing.card,
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        _details(context, condensed: false),
                        const SizedBox(height: AppSpacing.md),
                        _actions(),
                      ],
                    ),
                  ),
                ],
              ),
      ),
    );
  }
}
