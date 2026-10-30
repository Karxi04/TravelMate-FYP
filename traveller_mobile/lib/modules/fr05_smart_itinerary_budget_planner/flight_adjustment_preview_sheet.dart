import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';

class FlightAdjustmentPreviewSheet extends StatefulWidget {
  final ApiService api;
  final String tripId;
  final Map<String, dynamic>? initialPreview;
  final Map<String, dynamic> trip;

  const FlightAdjustmentPreviewSheet({
    super.key,
    required this.api,
    required this.tripId,
    this.initialPreview,
    required this.trip,
  });

  static Future<Map<String, dynamic>?> show({
    required BuildContext context,
    required ApiService api,
    required String tripId,
    Map<String, dynamic>? initialPreview,
    required Map<String, dynamic> trip,
  }) {
    return showModalBottomSheet<Map<String, dynamic>>(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) => FlightAdjustmentPreviewSheet(
        api: api,
        tripId: tripId,
        initialPreview: initialPreview,
        trip: trip,
      ),
    );
  }

  @override
  State<FlightAdjustmentPreviewSheet> createState() =>
      _FlightAdjustmentPreviewSheetState();
}

class _FlightAdjustmentPreviewSheetState
    extends State<FlightAdjustmentPreviewSheet> {
  Map<String, dynamic>? preview;
  bool loading = false;
  bool applying = false;
  bool refreshing = false;
  bool isStale = false;
  String? errorMessage;

  @override
  void initState() {
    super.initState();
    if (widget.initialPreview != null) {
      preview = Map<String, dynamic>.from(widget.initialPreview!);
    } else {
      _loadPreview();
    }
  }

  Future<void> _loadPreview() async {
    setState(() {
      loading = true;
      errorMessage = null;
      isStale = false;
    });
    try {
      final data = await widget.api.post(
        '/api/fr5/itineraries/${widget.tripId}/flight-adjustment/preview',
      );
      if (!mounted) return;
      final rawPreview = data['preview'] is Map
          ? Map<String, dynamic>.from(data['preview'] as Map)
          : <String, dynamic>{};
      setState(() {
        preview = rawPreview;
        loading = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        loading = false;
        if (e.statusCode == 404 ||
            '${e.message}'.toLowerCase().contains('not found')) {
          isStale = true;
          errorMessage =
              'Preview expired or server restarted. Please refresh the preview.';
        } else if (e.statusCode == 409 ||
            '${e.message}'.toLowerCase().contains('stale')) {
          isStale = true;
          errorMessage =
              'Your itinerary has changed. Refresh the preview to review the latest schedule.';
        } else {
          errorMessage = e.message.isNotEmpty ? e.message : e.toString();
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        loading = false;
        errorMessage = travellerErrorMessage(e);
      });
    }
  }

  Future<void> _refreshPreview() async {
    setState(() {
      refreshing = true;
      errorMessage = null;
    });
    try {
      final data = await widget.api.post(
        '/api/fr5/itineraries/${widget.tripId}/flight-adjustment/preview',
      );
      if (!mounted) return;
      final rawPreview = data['preview'] is Map
          ? Map<String, dynamic>.from(data['preview'] as Map)
          : <String, dynamic>{};
      setState(() {
        preview = rawPreview;
        isStale = false;
        refreshing = false;
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        refreshing = false;
        if (e.statusCode == 404 ||
            '${e.message}'.toLowerCase().contains('not found')) {
          isStale = true;
          errorMessage =
              'Preview expired or server restarted. Please refresh the preview.';
        } else if (e.statusCode == 409 ||
            '${e.message}'.toLowerCase().contains('stale')) {
          isStale = true;
          errorMessage =
              'Your itinerary has changed. Refresh the preview to review the latest schedule.';
        } else {
          errorMessage = e.message.isNotEmpty ? e.message : e.toString();
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        refreshing = false;
        errorMessage = travellerErrorMessage(e);
      });
    }
  }

  Future<void> _applyChanges() async {
    if (applying || isStale || preview == null) return;
    final previewId = preview!['previewId']?.toString();
    if (previewId == null || previewId.isEmpty) {
      setState(() {
        errorMessage = 'Preview ID is missing. Please refresh the preview.';
      });
      return;
    }

    setState(() {
      applying = true;
      errorMessage = null;
    });

    try {
      final data = await widget.api.post(
        '/api/fr5/itineraries/${widget.tripId}/flight-adjustment/apply',
        {'previewId': previewId},
      );
      if (!mounted) return;
      final updatedItinerary = data['itinerary'] is Map
          ? Map<String, dynamic>.from(data['itinerary'] as Map)
          : Map<String, dynamic>.from(data);
      Navigator.pop(context, {
        'applied': true,
        'itinerary': updatedItinerary,
      });
    } on ApiException catch (e) {
      if (!mounted) return;
      setState(() {
        applying = false;
        if (e.statusCode == 409 ||
            e.code == 'stale_preview' ||
            '${e.message}'.toLowerCase().contains('stale')) {
          isStale = true;
          errorMessage =
              'Your itinerary has changed. Refresh the preview to review the latest schedule.';
        } else if (e.statusCode == 404 ||
            '${e.message}'.toLowerCase().contains('not found')) {
          isStale = true;
          errorMessage =
              'Preview expired or server restarted. Please refresh the preview.';
        } else {
          errorMessage = e.message.isNotEmpty ? e.message : e.toString();
        }
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        applying = false;
        errorMessage = travellerErrorMessage(e);
      });
    }
  }

  Widget _buildStatusChip(bool canApply) {
    if (isStale) {
      return Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: AppColors.warningSoft,
          borderRadius: BorderRadius.circular(12),
          border: Border.all(color: AppColors.warning.withValues(alpha: 0.5)),
        ),
        child: const Text(
          'Stale Preview',
          style: TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w700,
            color: AppColors.warning,
          ),
        ),
      );
    }
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
      decoration: BoxDecoration(
        color: canApply ? AppColors.successSoft : AppColors.warningSoft,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(
          color: canApply
              ? AppColors.success.withValues(alpha: 0.5)
              : AppColors.warning.withValues(alpha: 0.5),
        ),
      ),
      child: Text(
        canApply ? 'Ready to apply' : 'Manual review required',
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: canApply ? AppColors.success : AppColors.warning,
        ),
      ),
    );
  }

  Widget _buildChangeCard(Map<String, dynamic> change) {
    final name = (change['activityName'] ?? 'Activity').toString();
    final kind = (change['kind'] ?? 'retained').toString().toLowerCase();
    final isProtected = change['protected'] == true;
    final reason = change['reason']?.toString();
    final from = change['from'] is Map ? change['from'] as Map : null;
    final to = change['to'] is Map ? change['to'] as Map : null;

    final bool isMoved = kind == 'moved' || kind == 'rescheduled';
    final bool isUnscheduled = kind == 'unscheduled';
    final bool isRetained = kind == 'retained';

    Color cardBorderColor = const Color(0xFFE2E8F0);
    Color badgeColor = const Color(0xFFEDF2F7);
    Color badgeTextColor = const Color(0xFF4A5568);
    String badgeLabel = 'Unchanged';

    if (isMoved) {
      cardBorderColor = AppColors.primary.withValues(alpha: 0.3);
      badgeColor = AppColors.primarySoft;
      badgeTextColor = AppColors.primary;
      badgeLabel = 'Rescheduled';
    } else if (isUnscheduled) {
      cardBorderColor = AppColors.warning.withValues(alpha: 0.3);
      badgeColor = AppColors.warningSoft;
      badgeTextColor = AppColors.warning;
      badgeLabel = 'Would become unscheduled';
    } else if (isRetained) {
      badgeLabel = 'Unchanged';
    }

    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: cardBorderColor),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Text(
                  name,
                  style: const TextStyle(
                    fontWeight: FontWeight.w800,
                    fontSize: 14,
                  ),
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 3),
                decoration: BoxDecoration(
                  color: badgeColor,
                  borderRadius: BorderRadius.circular(6),
                ),
                child: Text(
                  badgeLabel,
                  style: TextStyle(
                    fontSize: 11,
                    fontWeight: FontWeight.w700,
                    color: badgeTextColor,
                  ),
                ),
              ),
            ],
          ),
          if (isProtected) ...[
            const SizedBox(height: 6),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: const Color(0xFFFFF7ED),
                borderRadius: BorderRadius.circular(6),
                border: Border.all(color: const Color(0xFFFDBA74)),
              ),
              child: const Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(Icons.shield_outlined,
                      size: 14, color: Color(0xFFC2410C)),
                  SizedBox(width: 4),
                  Flexible(
                    child: Text(
                      'Protected Activity — Manual review required',
                      style: TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFFC2410C),
                      ),
                    ),
                  ),
                ],
              ),
            ),
          ],
          if (isMoved && from != null && to != null) ...[
            const SizedBox(height: 8),
            Row(
              children: [
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Current',
                        style: TextStyle(
                            fontSize: 11, color: InkWashColors.mutedInk),
                      ),
                      Text(
                        '${from['scheduledStartTime'] ?? '-'} - ${from['scheduledEndTime'] ?? '-'}',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                          decoration: TextDecoration.lineThrough,
                          color: InkWashColors.mutedInk,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(Icons.arrow_forward_rounded,
                    size: 16, color: InkWashColors.blueGrey),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.end,
                    children: [
                      const Text(
                        'Proposed',
                        style: TextStyle(
                            fontSize: 11, color: InkWashColors.mutedInk),
                      ),
                      Text(
                        '${to['scheduledStartTime'] ?? '-'} - ${to['scheduledEndTime'] ?? '-'}',
                        style: const TextStyle(
                          fontSize: 13,
                          fontWeight: FontWeight.w700,
                          color: AppColors.primary,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ],
          if (isRetained) ...[
            const SizedBox(height: 4),
            const Text(
              'Unchanged — fits within flight availability',
              style: TextStyle(fontSize: 12, color: InkWashColors.mutedInk),
            ),
          ],
          if (reason != null && reason.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              'Reason: $reason',
              style: const TextStyle(
                fontSize: 12,
                color: InkWashColors.mutedInk,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = preview;
    final canApply = p != null && p['canApply'] == true;
    final changes = (p?['changes'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final unscheduled = (p?['newlyUnscheduled'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final conflicts = (p?['remainingConflicts'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    final budgetBefore = p?['budgetBefore'] is Map ? p!['budgetBefore'] : null;
    final budgetAfter = p?['budgetAfter'] is Map ? p!['budgetAfter'] : null;

    final double screenHeight = MediaQuery.of(context).size.height;

    return Container(
      constraints: BoxConstraints(
        maxHeight: screenHeight * 0.9,
      ),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.stretch,
          children: [
            // Drag Handle & Header
            Padding(
              padding: const EdgeInsets.fromLTRB(20, 12, 16, 12),
              child: Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Text(
                          'Review flight-aware adjustment',
                          style: TextStyle(
                            fontSize: 18,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 2),
                        const Text(
                          'Review Itinerary Changes',
                          style: TextStyle(
                            fontSize: 12,
                            color: InkWashColors.mutedInk,
                            fontWeight: FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                  ),
                  if (p != null) _buildStatusChip(canApply),
                  IconButton(
                    icon: const Icon(Icons.close_rounded),
                    onPressed: () => Navigator.pop(context),
                  ),
                ],
              ),
            ),
            const Divider(height: 1),

            // Body
            Expanded(
              child: loading
                  ? const Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          CircularProgressIndicator(),
                          SizedBox(height: 16),
                          Text('Calculating flight-aware adjustment preview...'),
                        ],
                      ),
                    )
                  : ListView(
                      padding: const EdgeInsets.fromLTRB(20, 16, 20, 20),
                      children: [
                        // Stale / Expired Warning Banner
                        if (isStale || errorMessage != null) ...[
                          Container(
                            key: const ValueKey('preview-stale-warning'),
                            margin: const EdgeInsets.only(bottom: 16),
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.warningSoft,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(
                                color:
                                    AppColors.warning.withValues(alpha: 0.4),
                              ),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  children: [
                                    const Icon(Icons.warning_amber_rounded,
                                        size: 20, color: AppColors.warning),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        errorMessage ??
                                            'Your itinerary has changed. Refresh the preview to review the latest schedule.',
                                        style: const TextStyle(
                                          fontSize: 13,
                                          fontWeight: FontWeight.w700,
                                          color: AppColors.warning,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                                const SizedBox(height: 8),
                                Align(
                                  alignment: Alignment.centerRight,
                                  child: FilledButton.tonalIcon(
                                    key: const ValueKey('refresh-preview-btn'),
                                    onPressed:
                                        refreshing ? null : _refreshPreview,
                                    icon: refreshing
                                        ? const SizedBox(
                                            width: 14,
                                            height: 14,
                                            child: CircularProgressIndicator(
                                                strokeWidth: 2),
                                          )
                                        : const Icon(Icons.refresh_rounded,
                                            size: 16),
                                    label: const Text('Refresh preview'),
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],

                        // Planning Notice & Local Time
                        Container(
                          margin: const EdgeInsets.only(bottom: 16),
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(
                            color: InkWashColors.cream,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(color: const Color(0xFFE2E8F0)),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                canApply
                                    ? 'TravelMate proposes changes only on the flight-affected dates. Your current trip stays saved until you apply this preview.'
                                    : (p?['reason'] ??
                                            'The flight data is incomplete for a safe adjustment.')
                                        .toString(),
                                style: const TextStyle(
                                  fontSize: 13,
                                  height: 1.4,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 6),
                              const Text(
                                'Availability uses Penang local time and standard planning assumptions.',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: InkWashColors.mutedInk,
                                ),
                              ),
                            ],
                          ),
                        ),

                        // Proposed Changes Section
                        const Text(
                          'Proposed Activity Changes',
                          style: TextStyle(
                            fontSize: 15,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 8),
                        if (changes.isEmpty && canApply) ...[
                          const Padding(
                            padding: EdgeInsets.symmetric(vertical: 8),
                            child:
                                Text('No activity timing changes are needed.'),
                          ),
                        ] else ...[
                          ...changes.map(_buildChangeCard),
                        ],

                        // Would become unscheduled
                        if (unscheduled.isNotEmpty) ...[
                          const SizedBox(height: 16),
                          const Text(
                            'Would become unscheduled',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w900,
                              color: AppColors.warning,
                            ),
                          ),
                          const SizedBox(height: 6),
                          ...unscheduled.map(
                            (item) => Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Text(
                                '• ${item['activityName'] ?? item['activityId']}: ${item['unscheduledReason'] ?? 'Needs manual review'}',
                                style: const TextStyle(fontSize: 13),
                              ),
                            ),
                          ),
                        ],

                        // Remaining conflicts
                        if (conflicts.isNotEmpty) ...[
                          const SizedBox(height: 16),
                          const Text(
                            'Remaining conflicts',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w900,
                              color: AppColors.warning,
                            ),
                          ),
                          const SizedBox(height: 6),
                          ...conflicts.map(
                            (item) => Padding(
                              padding: const EdgeInsets.only(bottom: 4),
                              child: Text(
                                '• ${item['message'] ?? 'Manual review required'}',
                                style: const TextStyle(fontSize: 13),
                              ),
                            ),
                          ),
                        ],

                        // Budget impact
                        if (budgetBefore != null && budgetAfter != null) ...[
                          const SizedBox(height: 16),
                          const Text(
                            'Budget Impact',
                            style: TextStyle(
                              fontSize: 15,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          const SizedBox(height: 8),
                          Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: const Color(0xFFF8FAFC),
                              borderRadius: BorderRadius.circular(10),
                              border:
                                  Border.all(color: const Color(0xFFE2E8F0)),
                            ),
                            child: Row(
                              children: [
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      const Text(
                                        'Current Committed',
                                        style: TextStyle(
                                          fontSize: 11,
                                          color: InkWashColors.mutedInk,
                                        ),
                                      ),
                                      Text(
                                        'RM ${budgetBefore['total'] ?? '-'}',
                                        style: const TextStyle(
                                          fontSize: 14,
                                          fontWeight: FontWeight.w800,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const Icon(Icons.arrow_forward_rounded,
                                    size: 16, color: InkWashColors.blueGrey),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment: CrossAxisAlignment.end,
                                    children: [
                                      const Text(
                                        'After Adjustment',
                                        style: TextStyle(
                                          fontSize: 11,
                                          color: InkWashColors.mutedInk,
                                        ),
                                      ),
                                      Text(
                                        'RM ${budgetAfter['total'] ?? '-'}',
                                        style: const TextStyle(
                                          fontSize: 14,
                                          fontWeight: FontWeight.w800,
                                          color: AppColors.primary,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ],
                            ),
                          ),
                        ],
                      ],
                    ),
            ),

            // Bottom Action Bar
            Container(
              padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
              decoration: const BoxDecoration(
                color: Colors.white,
                border: Border(top: BorderSide(color: Color(0xFFE2E8F0))),
              ),
              child: Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: applying ? null : () => Navigator.pop(context),
                      child: const Text('Keep current plan'),
                    ),
                  ),
                  const SizedBox(width: 8),
                  if (isStale || !canApply) ...[
                    OutlinedButton(
                      key: const ValueKey('refresh-preview-btn-bottom'),
                      onPressed: (refreshing || applying)
                          ? null
                          : _refreshPreview,
                      child: refreshing
                          ? const SizedBox(
                              width: 14,
                              height: 14,
                              child: CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Refresh preview'),
                    ),
                    const SizedBox(width: 8),
                  ],
                  Expanded(
                    child: FilledButton(
                      key: const ValueKey('apply-flight-adjustment-btn'),
                      onPressed:
                          (canApply && !applying && !isStale && !loading)
                              ? _applyChanges
                              : null,
                      child: applying
                          ? const SizedBox(
                              width: 18,
                              height: 18,
                              child: CircularProgressIndicator(
                                strokeWidth: 2,
                                color: Colors.white,
                              ),
                            )
                          : const Text('Apply changes'),
                    ),
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
