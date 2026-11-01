import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class PackageActivityItem {
  final String name;
  final String? time;
  final String? location;
  final String? description;

  const PackageActivityItem({
    required this.name,
    this.time,
    this.location,
    this.description,
  });
}

class PackageTripDetailsScreen extends StatefulWidget {
  final String tripId;
  final ApiService? api;
  final Map<String, dynamic>? initialTrip;

  const PackageTripDetailsScreen({
    super.key,
    required this.tripId,
    this.api,
    this.initialTrip,
  });

  @override
  State<PackageTripDetailsScreen> createState() => _PackageTripDetailsScreenState();
}

class _PackageTripDetailsScreenState extends State<PackageTripDetailsScreen> {
  late final ApiService api;
  Map<String, dynamic>? trip;
  bool loading = true;
  String? loadError;
  int selectedDay = 1;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    if (widget.initialTrip != null) {
      trip = Map<String, dynamic>.from(widget.initialTrip!);
      loading = false;
    }
    Future.microtask(load);
  }

  @override
  void didUpdateWidget(covariant PackageTripDetailsScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.tripId != widget.tripId || oldWidget.initialTrip != widget.initialTrip) {
      if (widget.initialTrip != null) {
        setState(() {
          trip = Map<String, dynamic>.from(widget.initialTrip!);
          loading = false;
        });
      }
      load();
    }
  }

  Future<void> load() async {
    if (trip == null) {
      setState(() {
        loading = true;
        loadError = null;
      });
    }
    try {
      Map<String, dynamic>? found;
      try {
        final single = await api.get('/api/fr5/itineraries/${widget.tripId}');
        if (single is Map && single['itinerary'] is Map) {
          found = Map<String, dynamic>.from(single['itinerary'] as Map);
        }
      } catch (_) {
        // Fallback to list search
      }

      if (found == null) {
        final data = await api.get('/api/fr5/itineraries');
        final items = (data['items'] as List? ?? [])
            .whereType<Map>()
            .map((e) => Map<String, dynamic>.from(e))
            .toList();
        for (final item in items) {
          if (item['id'].toString() == widget.tripId) {
            found = item;
            break;
          }
        }
      }

      if (!mounted) return;
      setState(() {
        trip = found;
        if (found != null) {
          final totalDays = _totalTripDays(found);
          selectedDay = selectedDay.clamp(1, totalDays);
        } else {
          loadError = 'Package trip record could not be found.';
        }
      });
    } catch (_) {
      if (mounted) {
        setState(() => loadError = 'Could not load package trip details right now.');
      }
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Map<String, dynamic> get _snapshot {
    final raw = trip?['packageSnapshot'];
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return <String, dynamic>{};
  }

  int _totalTripDays(Map<String, dynamic> data) {
    final snap = data['packageSnapshot'] is Map
        ? Map<String, dynamic>.from(data['packageSnapshot'] as Map)
        : <String, dynamic>{};
    final snapDays = (snap['itineraryDays'] as List? ?? []).length;
    if (snapDays > 0) return snapDays;
    final duration = int.tryParse('${snap['durationDays'] ?? data['tripDays']}');
    if (duration != null && duration > 0) return duration;
    final sched = (data['dailySchedule'] as List? ?? []).length;
    return sched > 0 ? sched : 1;
  }

  List<Map<String, dynamic>> get _itineraryDays {
    final snapDays = (_snapshot['itineraryDays'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    if (snapDays.isNotEmpty) return snapDays;

    final schedule = (trip?['dailySchedule'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    if (schedule.isNotEmpty) {
      return schedule.map((item) {
        return {
          'dayNumber': item['dayNo'] ?? 1,
          'title': item['title'] ?? 'Day ${item['dayNo'] ?? 1}',
          'description': item['description'] ?? '',
          'activities': item['activities'] ?? [],
          'meals': item['meals'] ?? [],
          'accommodation': item['accommodation'],
          'transportNotes': item['transportNotes'],
        };
      }).toList();
    }

    final activities = (trip?['activities'] as List? ?? [])
        .whereType<Map>()
        .map((e) => Map<String, dynamic>.from(e))
        .toList();
    return [
      {
        'dayNumber': 1,
        'title': 'Day 1 Itinerary',
        'description': '',
        'activities': activities,
        'meals': [],
      }
    ];
  }

  Map<String, dynamic>? _dayData(int dayNum) {
    final days = _itineraryDays;
    for (final day in days) {
      final num = int.tryParse('${day['dayNumber'] ?? day['dayNo']}');
      if (num == dayNum) return day;
    }
    if (dayNum - 1 >= 0 && dayNum - 1 < days.length) {
      return days[dayNum - 1];
    }
    return null;
  }

  String _formatMoney(num? amount) {
    if (amount == null) return '0.00';
    return amount.toStringAsFixed(2);
  }

  List<String> _stringList(dynamic raw) {
    if (raw is List) {
      final result = <String>[];
      for (final e in raw) {
        if (e is Map) {
          final s = (e['title'] ?? e['name'] ?? e.toString()).toString().trim();
          if (s.isNotEmpty) result.add(s);
        } else if (e is String) {
          final lines = e.split(RegExp(r'\r?\n')).map((s) => s.trim()).where((s) => s.isNotEmpty);
          result.addAll(lines);
        } else if (e != null) {
          final s = e.toString().trim();
          if (s.isNotEmpty) result.add(s);
        }
      }
      return result;
    }
    if (raw is String && raw.trim().isNotEmpty) {
      return raw
          .split(RegExp(r'\r?\n'))
          .map((s) => s.trim())
          .where((s) => s.isNotEmpty)
          .toList();
    }
    return const [];
  }

  List<PackageActivityItem> _extractActivities(Map<String, dynamic>? currentDay) {
    if (currentDay == null) return const [];
    final raw = currentDay['activities'];
    final List<dynamic> list;
    if (raw is List) {
      list = raw;
    } else if (raw is String && raw.trim().isNotEmpty) {
      list = raw.trim().split(RegExp(r'\r?\n'));
    } else {
      list = const [];
    }

    final items = <PackageActivityItem>[];
    for (final entry in list) {
      if (entry == null) continue;
      if (entry is String) {
        final line = entry.trim();
        if (line.isEmpty) continue;
        // Check if line starts with a time prefix (e.g. "09:30 - George Town tour" or "09:30 AM: Tour")
        final match = RegExp(r'^(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\s*(?:[-:–—]\s*|\s+)(.+)$').firstMatch(line);
        if (match != null) {
          final timeStr = match.group(1)!.trim();
          final nameStr = match.group(2)!.trim();
          items.add(PackageActivityItem(
            time: timeStr,
            name: nameStr.isNotEmpty ? nameStr : line,
          ));
        } else {
          items.add(PackageActivityItem(
            time: null,
            name: line,
          ));
        }
      } else if (entry is Map) {
        final map = Map<String, dynamic>.from(entry);
        var name = (map['activityName'] ?? map['title'] ?? map['name'] ?? '').toString().trim();
        var time = (map['scheduledStartTime'] ?? map['timeSlot'] ?? map['time'] ?? map['scheduledTime'] ?? '').toString().trim();
        final desc = (map['description'] ?? '').toString().trim();
        final loc = (map['location'] ?? map['address'] ?? '').toString().trim();

        final match = RegExp(r'^(\d{1,2}:\d{2}(?:\s*[AaPp][Mm])?)\s*(?:[-:–—]\s*|\s+)(.+)$').firstMatch(name);
        if (match != null) {
          if (time.isEmpty) {
            time = match.group(1)!.trim();
          }
          name = match.group(2)!.trim();
        }

        if (name.isNotEmpty) {
          items.add(PackageActivityItem(
            name: name,
            time: time.isNotEmpty ? time : null,
            description: desc.isNotEmpty ? desc : null,
            location: loc.isNotEmpty ? loc : null,
          ));
        }
      }
    }
    return items;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: const Text('Package Trip Details'),
        actions: [
          IconButton(
            tooltip: 'Refresh',
            icon: const Icon(Icons.refresh_rounded),
            onPressed: load,
          ),
        ],
      ),
      body: _buildBody(),
    );
  }

  Widget _buildBody() {
    if (loading && trip == null) {
      return const AppLoadingState(message: 'Loading purchased package trip…');
    }
    if (loadError != null && trip == null) {
      return AppErrorState(message: loadError!, onRetry: load);
    }
    if (trip == null) {
      return const TravelEmptyState(
        icon: Icons.luggage_outlined,
        title: 'Trip not found',
        message: 'This package trip is unavailable.',
      );
    }

    final snap = _snapshot;
    final totalDays = _totalTripDays(trip!);
    final title = (snap['title'] ?? trip!['title'] ?? 'Purchased Tourism Package').toString();
    final destination = (snap['destination'] ?? trip!['destinationArea'] ?? '').toString();
    final coverImage = (snap['coverImage'] ?? snap['imageUrl'] ?? trip!['coverImage'] ?? '').toString();
    final orderId = (trip!['checkoutOrderId'] ?? trip!['id'] ?? '').toString();
    final paidAmount = num.tryParse('${trip!['paidTotal'] ?? snap['price'] ?? 0}') ?? 0;
    final currency = (trip!['currency'] ?? snap['currency'] ?? 'MYR').toString().toUpperCase();
    final startDate = (trip!['startDate'] ?? snap['selectedDepartureDate'] ?? '').toString();

    final rawParticipants = trip!['participants'] ?? snap['participants'];
    final participantsMap = rawParticipants is Map ? Map<String, dynamic>.from(rawParticipants) : <String, dynamic>{};
    final adults = int.tryParse('${participantsMap['adults']}') ?? 1;
    final children = int.tryParse('${participantsMap['children']}') ?? 0;

    final operatorName = (snap['operatorName'] ?? snap['operator'] ?? 'Verified Tourism Operator').toString();
    final meetingPoint = (snap['meetingPoint'] ?? '').toString().trim();
    final cancellationPolicy = (snap['cancellationPolicy'] ?? '').toString().trim();
    final importantNotes = _stringList(snap['importantNotes']);
    final includedServices = _stringList(snap['includedServices']);
    final excludedServices = _stringList(snap['excludedServices']);
    final highlights = _stringList(snap['highlights']);

    return RefreshIndicator(
      onRefresh: load,
      child: ListView(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 40),
        children: [
          // 1. Header Card with Cover Image and Badges
          InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (coverImage.isNotEmpty)
                  ClipRRect(
                    borderRadius: BorderRadius.circular(14),
                    child: TravelPlaceImage(
                      place: {'coverImage': coverImage, 'title': title},
                      height: 180,
                      width: double.infinity,
                    ),
                  ),
                if (coverImage.isNotEmpty) const SizedBox(height: 14),
                Wrap(
                  spacing: 8,
                  runSpacing: 8,
                  children: [
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: AppColors.successSoft,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.verified_rounded, size: 14, color: AppColors.success),
                          SizedBox(width: 4),
                          Flexible(
                            child: Text(
                              'Purchased Package',
                              style: TextStyle(
                                color: AppColors.success,
                                fontWeight: FontWeight.w700,
                                fontSize: 12,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                      decoration: BoxDecoration(
                        color: AppColors.primarySoft,
                        borderRadius: BorderRadius.circular(8),
                      ),
                      child: Text(
                        '$totalDays Days · ${totalDays > 1 ? '${totalDays - 1} Nights' : 'Day Trip'}',
                        style: const TextStyle(
                          color: AppColors.primaryStrong,
                          fontWeight: FontWeight.w600,
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                Text(
                  title,
                  style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                        fontWeight: FontWeight.w800,
                      ),
                ),
                if (destination.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      const Icon(Icons.location_on_outlined, size: 16, color: AppColors.textSecondary),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          destination,
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                color: AppColors.textSecondary,
                              ),
                        ),
                      ),
                    ],
                  ),
                ],
                const SizedBox(height: 6),
                Row(
                  children: [
                    const Icon(Icons.business_outlined, size: 16, color: AppColors.textSecondary),
                    const SizedBox(width: 4),
                    Expanded(
                      child: Text(
                        'Operator: $operatorName',
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                    ),
                  ],
                ),
                if (startDate.isNotEmpty) ...[
                  const SizedBox(height: 4),
                  Row(
                    children: [
                      const Icon(Icons.calendar_today_outlined, size: 16, color: AppColors.textSecondary),
                      const SizedBox(width: 4),
                      Expanded(
                        child: Text(
                          'Departure: $startDate',
                          style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                      ),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 16),

          // 2. Booking & Supplier Status Card
          _buildBookingSummaryCard(
            orderId: orderId,
            paidAmount: paidAmount,
            currency: currency,
            adults: adults,
            children: children,
            priceBasis: (snap['priceBasis'] ?? '').toString(),
            supplierStatus: (trip!['supplierReservationStatus'] ?? 'pending').toString(),
          ),
          const SizedBox(height: 16),

          // 3. Overview Description & Meeting Point
          if ((snap['description'] ?? trip!['description'] ?? '').toString().isNotEmpty ||
              meetingPoint.isNotEmpty)
            _buildOverviewCard(
              description: (snap['description'] ?? trip!['description'] ?? '').toString(),
              meetingPoint: meetingPoint,
            ),
          if ((snap['description'] ?? trip!['description'] ?? '').toString().isNotEmpty ||
              meetingPoint.isNotEmpty)
            const SizedBox(height: 16),

          // 4. Day-by-Day Itinerary Section
          _buildItinerarySection(totalDays),
          const SizedBox(height: 16),

          // 5. Inclusions & Exclusions Card
          if (includedServices.isNotEmpty || excludedServices.isNotEmpty)
            _buildInclusionsCard(includedServices, excludedServices),
          if (includedServices.isNotEmpty || excludedServices.isNotEmpty)
            const SizedBox(height: 16),

          // 6. Highlights & Policies Card
          if (highlights.isNotEmpty || cancellationPolicy.isNotEmpty || importantNotes.isNotEmpty)
            _buildPoliciesCard(
              highlights: highlights,
              cancellationPolicy: cancellationPolicy,
              importantNotes: importantNotes,
            ),
          if (highlights.isNotEmpty || cancellationPolicy.isNotEmpty || importantNotes.isNotEmpty)
            const SizedBox(height: 16),

          // 7. Read-Only Guarantee Notice
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: AppColors.surface,
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppColors.divider),
            ),
            child: Row(
              children: [
                const Icon(Icons.lock_outline_rounded, color: AppColors.textSecondary, size: 20),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    'This purchased tourism package is managed directly by the operator. It cannot be altered or recalculated by the smart planner.',
                    style: Theme.of(context).textTheme.bodySmall?.copyWith(
                          color: AppColors.textSecondary,
                        ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOrderReferenceTile(String orderId) {
    final displayId = orderId.isNotEmpty ? orderId : 'N/A';
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
      decoration: BoxDecoration(
        color: AppColors.surfaceElevated,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  'Order Reference',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                        fontWeight: FontWeight.w600,
                      ),
                ),
              ),
              const SizedBox(width: 8),
              if (orderId.isNotEmpty)
                InkWell(
                  borderRadius: BorderRadius.circular(6),
                  onTap: () {
                    Clipboard.setData(ClipboardData(text: orderId));
                    ScaffoldMessenger.of(context).showSnackBar(
                      const SnackBar(
                        content: Text('Order reference copied to clipboard'),
                        duration: Duration(seconds: 2),
                        behavior: SnackBarBehavior.floating,
                      ),
                    );
                  },
                  child: const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4, vertical: 2),
                    child: Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(Icons.copy_rounded, size: 13, color: AppColors.primaryStrong),
                        SizedBox(width: 4),
                        Text(
                          'Copy',
                          style: TextStyle(
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                            color: AppColors.primaryStrong,
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
            ],
          ),
          const SizedBox(height: 6),
          SelectableText(
            displayId,
            style: const TextStyle(
              fontFamily: 'monospace',
              fontSize: 12,
              fontWeight: FontWeight.w600,
              color: AppColors.textPrimary,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildBookingSummaryCard({
    required String orderId,
    required num paidAmount,
    required String currency,
    required int adults,
    required int children,
    required String priceBasis,
    required String supplierStatus,
  }) {
    final basisLabel = priceBasis == 'per_group' ? 'Per Group' : 'Per Person';
    final isConfirmedSupplier = const {'confirmed', 'operator_attested'}
        .contains(supplierStatus.trim().toLowerCase());
    final supplierMessage = switch (supplierStatus.trim().toLowerCase()) {
      'confirmed' => 'Reservation confirmed by operator.',
      'operator_attested' =>
        'The operator has recorded supplier arrangements. These references have not been verified directly with suppliers by TravelMate.',
      'declined' =>
        'The operator is unable to fulfill this booking. Check your order and contact the operator for assistance. No refund is confirmed by this notice.',
      'not_required' =>
        'The operator has marked this Package Trip ready. No supplier reservations are required for the included services.',
      _ =>
        'Test payment recorded. Your Package Trip is available in TravelMate. No external supplier reservation has been created.',
    };

    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.receipt_long_outlined, color: AppColors.primaryStrong, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Booking & Payment Summary',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const Divider(height: 20),
          _buildOrderReferenceTile(orderId),
          _summaryRow(
            'Participants',
            '$adults ${adults == 1 ? 'Adult' : 'Adults'}${children > 0 ? ', $children ${children == 1 ? 'Child' : 'Children'}' : ''}',
          ),
          const SizedBox(height: 4),
          _summaryRow('Pricing Basis', basisLabel),
          const SizedBox(height: 4),
          _summaryRow(
            'Total Paid',
            '$currency ${_formatMoney(paidAmount)}',
            valueStyle: const TextStyle(fontWeight: FontWeight.w800, color: AppColors.success),
          ),
          const SizedBox(height: 12),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: isConfirmedSupplier ? AppColors.successSoft : AppColors.surfaceElevated,
              borderRadius: BorderRadius.circular(8),
              border: Border.all(
                color: isConfirmedSupplier ? AppColors.success.withValues(alpha: 0.4) : AppColors.divider,
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(
                  isConfirmedSupplier ? Icons.verified_rounded : Icons.info_outline_rounded,
                  size: 16,
                  color: isConfirmedSupplier ? AppColors.success : AppColors.textSecondary,
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    supplierMessage,
                    style: TextStyle(
                      color: isConfirmedSupplier ? AppColors.success : AppColors.textPrimary,
                      fontWeight: FontWeight.w500,
                      fontSize: 12,
                      height: 1.35,
                    ),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
            decoration: BoxDecoration(
              color: AppColors.infoSoft,
              borderRadius: BorderRadius.circular(8),
            ),
            child: const Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline_rounded, size: 16, color: AppColors.info),
                SizedBox(width: 8),
                Expanded(
                  child: Text(
                    'Stripe Test Mode: This booking was processed in Stripe Test Mode. No real charges were incurred.',
                    style: TextStyle(
                      color: AppColors.info,
                      fontSize: 11,
                      fontWeight: FontWeight.w500,
                      height: 1.3,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _summaryRow(String label, String value, {TextStyle? valueStyle}) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.baseline,
        textBaseline: TextBaseline.alphabetic,
        children: [
          Text(
            label,
            style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Text(
              value,
              textAlign: TextAlign.end,
              style: valueStyle ??
                  Theme.of(context).textTheme.bodySmall?.copyWith(fontWeight: FontWeight.w600),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildOverviewCard({
    required String description,
    required String meetingPoint,
  }) {
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.explore_outlined, color: AppColors.primaryStrong, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Package Overview',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          if (description.isNotEmpty) ...[
            const SizedBox(height: 10),
            Text(
              description,
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    height: 1.45,
                  ),
            ),
          ],
          if (meetingPoint.isNotEmpty) ...[
            const Divider(height: 20),
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.place_outlined, size: 18, color: AppColors.primaryStrong),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text(
                        'Meeting Point / Assembly',
                        style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        meetingPoint,
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildItinerarySection(int totalDays) {
    final currentDay = _dayData(selectedDay);
    final dayTitle = (currentDay?['title'] ?? 'Day $selectedDay').toString();
    final dayDesc = (currentDay?['description'] ?? '').toString();
    final activities = _extractActivities(currentDay);
    final meals = _stringList(currentDay?['meals']);
    final accommodation = (currentDay?['accommodation'] ?? '').toString().trim();
    final transportNotes = (currentDay?['transportNotes'] ?? '').toString().trim();

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Expanded(
              child: Text(
                'Day-by-Day Itinerary',
                style: Theme.of(context).textTheme.titleLarge?.copyWith(fontWeight: FontWeight.w800),
              ),
            ),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
              decoration: BoxDecoration(
                color: AppColors.primarySoft,
                borderRadius: BorderRadius.circular(6),
              ),
              child: const Text(
                'Original Schedule',
                style: TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.w600,
                  color: AppColors.primaryStrong,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 10),

        // Day Selector Tabs
        SingleChildScrollView(
          scrollDirection: Axis.horizontal,
          child: Row(
            children: List.generate(totalDays, (index) {
              final dayIndex = index + 1;
              final isSelected = selectedDay == dayIndex;
              return Padding(
                padding: const EdgeInsets.only(right: 8),
                child: ChoiceChip(
                  label: Text('Day $dayIndex'),
                  selected: isSelected,
                  onSelected: (selected) {
                    if (selected) setState(() => selectedDay = dayIndex);
                  },
                  selectedColor: AppColors.primaryStrong,
                  labelStyle: TextStyle(
                    color: isSelected ? Colors.white : AppColors.textPrimary,
                    fontWeight: isSelected ? FontWeight.w700 : FontWeight.w500,
                  ),
                ),
              );
            }),
          ),
        ),
        const SizedBox(height: 12),

        // Day Details Card
        InkCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                dayTitle,
                style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w800),
              ),
              if (dayDesc.isNotEmpty) ...[
                const SizedBox(height: 4),
                Text(
                  dayDesc,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
                ),
              ],
              const SizedBox(height: 14),

              // Activity Items (Preserving original sequence and times)
              if (activities.isEmpty)
                const Padding(
                  padding: EdgeInsets.symmetric(vertical: 12),
                  child: Text(
                    'No scheduled activities listed for this day.',
                    style: TextStyle(fontStyle: FontStyle.italic, color: AppColors.textSecondary),
                  ),
                )
              else
                ...activities.asMap().entries.map((entry) {
                  final index = entry.key;
                  final act = entry.value;

                  return Padding(
                    padding: const EdgeInsets.only(bottom: 12),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Column(
                          children: [
                            CircleAvatar(
                              radius: 14,
                              backgroundColor: AppColors.primarySoft,
                              child: Text(
                                '${index + 1}',
                                style: const TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w700,
                                  color: AppColors.primaryStrong,
                                ),
                              ),
                            ),
                            if (index < activities.length - 1)
                              Container(
                                width: 2,
                                height: 36,
                                color: AppColors.divider,
                              ),
                          ],
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Container(
                            padding: const EdgeInsets.all(12),
                            decoration: BoxDecoration(
                              color: AppColors.surfaceElevated,
                              borderRadius: BorderRadius.circular(10),
                              border: Border.all(color: AppColors.divider),
                            ),
                            child: Column(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    Expanded(
                                      child: Text(
                                        act.name,
                                        style: const TextStyle(
                                          fontWeight: FontWeight.w700,
                                          fontSize: 14,
                                        ),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    if (act.time != null && act.time!.isNotEmpty)
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 3),
                                        decoration: BoxDecoration(
                                          color: AppColors.primarySoft,
                                          borderRadius: BorderRadius.circular(6),
                                        ),
                                        child: Row(
                                          mainAxisSize: MainAxisSize.min,
                                          children: [
                                            const Icon(Icons.schedule_rounded, size: 12, color: AppColors.primaryStrong),
                                            const SizedBox(width: 4),
                                            Text(
                                              act.time!,
                                              style: const TextStyle(
                                                fontSize: 11,
                                                fontWeight: FontWeight.w700,
                                                color: AppColors.primaryStrong,
                                              ),
                                            ),
                                          ],
                                        ),
                                      )
                                    else
                                      Container(
                                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                                        decoration: BoxDecoration(
                                          color: AppColors.surface,
                                          borderRadius: BorderRadius.circular(4),
                                          border: Border.all(color: AppColors.divider),
                                        ),
                                        child: const Text(
                                          'Time not specified',
                                          style: TextStyle(
                                            fontSize: 10,
                                            fontStyle: FontStyle.italic,
                                            color: AppColors.textSecondary,
                                          ),
                                        ),
                                      ),
                                  ],
                                ),
                                if (act.location != null && act.location!.isNotEmpty) ...[
                                  const SizedBox(height: 4),
                                  Row(
                                    children: [
                                      const Icon(Icons.pin_drop_outlined, size: 14, color: AppColors.textSecondary),
                                      const SizedBox(width: 4),
                                      Expanded(
                                        child: Text(
                                          act.location!,
                                          style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                                        ),
                                      ),
                                    ],
                                  ),
                                ],
                                if (act.description != null && act.description!.isNotEmpty) ...[
                                  const SizedBox(height: 6),
                                  Text(
                                    act.description!,
                                    style: const TextStyle(fontSize: 13, height: 1.4),
                                  ),
                                ],
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  );
                }),

              // Meals for this day
              if (meals.isNotEmpty) ...[
                const Divider(height: 20),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.restaurant_rounded, size: 16, color: AppColors.primaryStrong),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Meals Included: ${meals.join(', ')}',
                        style: const TextStyle(fontSize: 12, fontWeight: FontWeight.w600),
                      ),
                    ),
                  ],
                ),
              ],

              // Accommodation notes for this day
              if (accommodation.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.hotel_outlined, size: 16, color: AppColors.primaryStrong),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Stay: $accommodation',
                        style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                      ),
                    ),
                  ],
                ),
              ],

              // Transport notes for this day
              if (transportNotes.isNotEmpty) ...[
                const SizedBox(height: 8),
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.directions_bus_outlined, size: 16, color: AppColors.primaryStrong),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        'Transport: $transportNotes',
                        style: const TextStyle(fontSize: 12, color: AppColors.textSecondary),
                      ),
                    ),
                  ],
                ),
              ],
            ],
          ),
        ),
      ],
    );
  }

  Widget _buildInclusionsCard(List<String> inclusions, List<String> exclusions) {
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.checklist_rounded, color: AppColors.primaryStrong, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Inclusions & Exclusions',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const Divider(height: 20),
          if (inclusions.isNotEmpty) ...[
            const Text(
              'What’s Included',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: AppColors.success),
            ),
            const SizedBox(height: 6),
            ...inclusions.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 5),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.check_circle_outline, size: 16, color: AppColors.success),
                      const SizedBox(width: 8),
                      Expanded(child: Text(item, style: const TextStyle(fontSize: 13))),
                    ],
                  ),
                )),
          ],
          if (inclusions.isNotEmpty && exclusions.isNotEmpty) const SizedBox(height: 12),
          if (exclusions.isNotEmpty) ...[
            const Text(
              'What’s Not Included',
              style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13, color: AppColors.textSecondary),
            ),
            const SizedBox(height: 6),
            ...exclusions.map((item) => Padding(
                  padding: const EdgeInsets.only(bottom: 5),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Icon(Icons.cancel_outlined, size: 16, color: AppColors.textSecondary),
                      const SizedBox(width: 8),
                      Expanded(
                        child: Text(
                          item,
                          style: const TextStyle(fontSize: 13, color: AppColors.textSecondary),
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ],
      ),
    );
  }

  Widget _buildPoliciesCard({
    required List<String> highlights,
    required String cancellationPolicy,
    required List<String> importantNotes,
  }) {
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.policy_outlined, color: AppColors.primaryStrong, size: 20),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  'Highlights & Operator Policies',
                  style: Theme.of(context).textTheme.titleMedium?.copyWith(fontWeight: FontWeight.w700),
                ),
              ),
            ],
          ),
          const Divider(height: 20),
          if (highlights.isNotEmpty) ...[
            const Text('Package Highlights', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            const SizedBox(height: 6),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: highlights.map((h) => Chip(
                    label: Text(h, style: const TextStyle(fontSize: 11)),
                    backgroundColor: AppColors.surfaceElevated,
                    padding: EdgeInsets.zero,
                  )).toList(),
            ),
            const SizedBox(height: 12),
          ],
          if (cancellationPolicy.isNotEmpty) ...[
            const Text('Cancellation Policy', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            const SizedBox(height: 4),
            Text(
              cancellationPolicy,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
            ),
            const SizedBox(height: 12),
          ],
          if (importantNotes.isNotEmpty) ...[
            const Text('Important Notes', style: TextStyle(fontWeight: FontWeight.w700, fontSize: 13)),
            const SizedBox(height: 6),
            ...importantNotes.map((note) => Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      const Text('• ', style: TextStyle(fontWeight: FontWeight.bold)),
                      Expanded(
                        child: Text(
                          note,
                          style: Theme.of(context).textTheme.bodySmall?.copyWith(color: AppColors.textSecondary),
                        ),
                      ),
                    ],
                  ),
                )),
          ],
        ],
      ),
    );
  }
}
