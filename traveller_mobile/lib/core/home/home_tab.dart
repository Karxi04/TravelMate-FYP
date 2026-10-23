import 'dart:math' as math;

import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../core/navigation/app_shell_navigation.dart';
import '../../modules/fr02_travel_preference/preferences_screen.dart';
import '../../modules/fr03_destination_search_information/destination_details_screen.dart';
import '../../modules/fr03_destination_search_information/explore_tab.dart';
import '../../modules/fr04_hybrid_recommendation/recommendation_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/package_trip_details_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/personalized_planning_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/trip_details_screen.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../../modules/fr06_weather_forecast/weather_screen.dart';
import '../../modules/fr07_flight_search/flight_screen.dart';
import '../../modules/fr08_hotel_booking/car_rental_screen.dart';
import '../../modules/fr08_hotel_booking/hotel_screen.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/recommendation_card.dart';
import '../../widgets/travel_widgets.dart';
import '../operator_content/campaign_details_screen.dart';
import '../operator_content/package_details_screen.dart';

class HomeTab extends StatefulWidget {
  final ApiService? api;

  const HomeTab({super.key, this.api});

  @override
  State<HomeTab> createState() => _HomeTabState();
}

class _HomeTabState extends State<HomeTab> {
  late final ApiService api;
  final searchController = TextEditingController();

  Map<String, dynamic>? profile;
  Map<String, dynamic>? preferences;
  List<dynamic> trips = [];
  List<dynamic> recommendations = [];
  List<dynamic> tourismPackages = [];
  List<dynamic> promotionalCampaigns = [];

  bool loadingCore = true;
  bool loadingForYou = true;
  bool loadingSharedContent = true;
  bool _recommendationRequestInFlight = false;
  bool _sharedContentRequestInFlight = false;
  String? coreError;
  String? recommendationError;
  String recommendationSource = '';
  String recommendationGenerationId = '';
  Map<String, String> feedbackByDestination = {};
  final Set<String> feedbackInFlight = {};

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(loadSummary);
  }

  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }

  Future<_LoadResult> _capture(Future<dynamic> request) async {
    try {
      return _LoadResult(data: await request);
    } catch (error) {
      return _LoadResult(error: error);
    }
  }

  Future<void> _loadCoreData() async {
    if (mounted) setState(() => loadingCore = true);
    final results = await Future.wait([
      _capture(api.get('/api/fr1/me')),
      _capture(api.get('/api/fr5/itineraries')),
      _capture(api.get('/api/fr2/preferences')),
    ]);
    if (!mounted) return;

    final profileData = results[0].data;
    final tripData = results[1].data;
    final preferenceData = results[2].data;
    final failures = results.where((result) => result.error != null).length;

    setState(() {
      if (profileData is Map && profileData['profile'] is Map) {
        profile = Map<String, dynamic>.from(profileData['profile'] as Map);
      }
      if (tripData is Map) trips = tripData['items'] as List? ?? trips;
      if (preferenceData is Map && preferenceData['preferences'] is Map) {
        preferences = Map<String, dynamic>.from(
          preferenceData['preferences'] as Map,
        );
      }
      loadingCore = false;
      coreError = failures == 0
          ? null
          : failures == results.length
              ? 'We could not load your travel profile and trips.'
              : 'Some account details could not be refreshed.';
    });
  }

  Future<void> loadSummary() async {
    await _loadCoreData();
    await Future.wait([
      loadRecommendations(),
      loadPreferenceFeedback(),
      loadSharedContent(),
    ]);
  }

  Future<void> refreshHome() async {
    await Future.wait([
      _loadCoreData(),
      loadRecommendations(),
      loadPreferenceFeedback(),
      loadSharedContent(),
    ]);
  }

  Future<void> loadRecommendations({bool regenerate = false}) async {
    if (_recommendationRequestInFlight) return;
    _recommendationRequestInFlight = true;
    if (mounted) {
      setState(() {
        loadingForYou = true;
        recommendationError = null;
      });
    }

    try {
      dynamic data;
      if (regenerate) {
        data = await api.post('/api/fr4/recommendations/generate', {
          'destinationArea': 'Malaysia',
        });
      } else {
        data = await api.get('/api/fr4/recommendations');
        final existing = data is Map ? data['recommendations'] as List? : null;
        if ((existing == null || existing.isEmpty) && preferences != null) {
          data = await api.post('/api/fr4/recommendations/generate', {
            'destinationArea': 'Malaysia',
          });
        }
      }
      if (!mounted || data is! Map) return;
      setState(() {
        recommendations = data['recommendations'] as List? ?? [];
        recommendationSource = (data['source'] ?? '').toString();
        recommendationGenerationId = (data['recommendationGenerationId'] ??
                data['snapshot']?['recommendationGenerationId'] ??
                '')
            .toString();
      });
    } catch (error) {
      if (regenerate) {
        try {
          final existing = await api.get('/api/fr4/recommendations');
          if (mounted && existing is Map) {
            final cached = existing['recommendations'] as List? ?? [];
            setState(() {
              if (cached.isNotEmpty) recommendations = cached;
              recommendationSource = (existing['source'] ?? '').toString();
              recommendationGenerationId =
                  (existing['recommendationGenerationId'] ??
                          existing['snapshot']?['recommendationGenerationId'] ??
                          '')
                      .toString();
              recommendationError = cached.isEmpty
                  ? _message(error)
                  : 'Recommendations could not be refreshed. Showing your latest saved results.';
            });
            return;
          }
        } catch (_) {}
      }
      if (mounted) setState(() => recommendationError = _message(error));
    } finally {
      _recommendationRequestInFlight = false;
      if (mounted) setState(() => loadingForYou = false);
    }
  }

  Future<void> loadPreferenceFeedback() async {
    try {
      final data = await api.get('/api/fr4/preference-feedback');
      if (!mounted || data is! Map || data['learning'] is! Map) return;
      final current = Map<String, dynamic>.from(
        data['learning']['currentFeedback'] as Map? ?? const {},
      );
      setState(() {
        feedbackByDestination = current.map(
          (key, value) => MapEntry(key, value.toString()),
        );
      });
    } catch (_) {
      // Home remains useful when preference learning is temporarily unavailable.
    }
  }

  Future<void> loadSharedContent() async {
    if (_sharedContentRequestInFlight) return;
    _sharedContentRequestInFlight = true;
    if (mounted) setState(() => loadingSharedContent = true);
    try {
      final results = await Future.wait([
        api.get('/api/public/tourism-packages'),
        api.get('/api/public/promotional-campaigns'),
      ]);
      if (!mounted) return;
      final packagesData = results[0];
      final campaignsData = results[1];
      final campaigns = campaignsData is Map
          ? campaignsData['items'] as List? ?? []
          : <dynamic>[];
      final packages = packagesData is Map
          ? (packagesData['items'] as List? ?? []).map((raw) {
              final package = Map<String, dynamic>.from(raw as Map);
              final packageId = (package['id'] ?? '').toString();
              package['activeCampaigns'] = campaigns
                  .where((campaign) =>
                      campaign is Map &&
                      (campaign['packageId'] ?? '').toString() == packageId)
                  .toList();
              return package;
            }).toList()
          : <dynamic>[];
      setState(() {
        tourismPackages = packages;
        promotionalCampaigns = campaigns;
      });
    } catch (_) {
      // Partner inspiration is optional and does not block the core Home flow.
    } finally {
      _sharedContentRequestInFlight = false;
      if (mounted) setState(() => loadingSharedContent = false);
    }
  }

  String _message(Object error) {
    return error.toString().replaceFirst('Exception: ', '');
  }

  String get firstName {
    final value = (profile?['name'] ?? '').toString().trim();
    if (value.isNotEmpty) return value.split(' ').first;
    try {
      final email = FirebaseAuth.instance.currentUser?.email ?? '';
      if (email.contains('@')) return email.split('@').first;
    } catch (_) {}
    return 'Traveller';
  }

  String get greeting {
    final hour = DateTime.now().hour;
    if (hour < 12) return 'Good morning';
    if (hour < 18) return 'Good afternoon';
    return 'Good evening';
  }

  List<String> get interests => (preferences?['interests'] as List? ?? [])
      .map((value) => value.toString().trim())
      .where((value) => value.isNotEmpty)
      .toList();

  String get travelPersonality => (preferences?['travelPersonality'] ??
          preferences?['travelType'] ??
          'Your travel style')
      .toString();

  String get preferenceSummary {
    final parts = <String>[
      ...interests.take(2),
      if ((preferences?['travelPace'] ?? '').toString().trim().isNotEmpty)
        '${preferences!['travelPace']} pace',
    ];
    return parts.isEmpty ? 'Set your interests and pace' : parts.join(' · ');
  }

  Map<String, dynamic>? get continuationTrip {
    const visibleStates = {
      'draft',
      'generating',
      'planned',
      'generation_failed',
    };
    for (final raw in trips) {
      if (raw is! Map) continue;
      final trip = Map<String, dynamic>.from(raw);
      final status = (trip['status'] ?? 'draft').toString();
      if (visibleStates.contains(status)) return trip;
    }
    return null;
  }

  int _tripDays(Map<String, dynamic> trip) {
    final explicit = int.tryParse('${trip['tripDays'] ?? ''}');
    if (explicit != null && explicit > 0) return explicit;
    final start = DateTime.tryParse((trip['startDate'] ?? '').toString());
    final end = DateTime.tryParse((trip['endDate'] ?? '').toString());
    if (start != null && end != null) {
      return math.max(1, end.difference(start).inDays + 1);
    }
    return 1;
  }

  String? _budgetSummary(Map<String, dynamic> trip) {
    final estimate = trip['budgetEstimate'];
    if (estimate is! Map || estimate['total'] == null) return null;
    final total = estimate['total'];
    final limit = estimate['limit'] ?? trip['budgetLimit'];
    return limit == null
        ? 'RM $total estimated'
        : 'RM $total of RM $limit estimated';
  }

  Future<void> open(
    Widget screen, {
    bool refreshCoreOnReturn = false,
  }) async {
    await Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
    if (refreshCoreOnReturn && mounted) await _loadCoreData();
  }

  void openTripsTab() {
    if (!AppShellNavigation.select(context, AppShellTab.trips)) {
      open(const TripsTab(), refreshCoreOnReturn: true);
    }
  }

  String destinationId(Map<String, dynamic> item) => (item['destinationId'] ??
          item['place_id'] ??
          item['id'] ??
          item['title'] ??
          item['name'] ??
          '')
      .toString();

  Future<void> submitPreferenceFeedback(
    Map<String, dynamic> item,
    String feedbackType,
  ) async {
    final id = destinationId(item);
    if (id.isEmpty || feedbackInFlight.contains(id)) return;
    setState(() => feedbackInFlight.add(id));
    try {
      final data = await api.post('/api/fr4/preference-feedback', {
        'destinationId': id,
        'recommendationGenerationId': recommendationGenerationId,
        'feedbackType': feedbackType,
        'sourceContext': 'home',
        if (recommendationGenerationId.isEmpty)
          'destinationConcepts': item['destinationConcepts'],
      });
      if (data is Map && data['ok'] == false) {
        throw Exception(data['error'] ?? 'Feedback could not be saved.');
      }
      if (!mounted) return;
      setState(() => feedbackByDestination[id] = feedbackType);
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text(
            'Thanks — this will help improve future recommendations.',
          ),
        ),
      );
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => feedbackInFlight.remove(id));
    }
  }

  Future<void> addToTrip(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final available = (data['items'] as List? ?? [])
          .whereType<Map>()
          .where((t) => t['tripType'] != 'package' && t['packageTrip'] != true)
          .toList();
      if (!mounted) return;
      if (available.isEmpty) {
        final plan = await showDialog<bool>(
          context: context,
          builder: (context) => AlertDialog(
            title: const Text('Plan a trip first'),
            content: const Text(
              'Create your trip plan, then add this recommendation to it.',
            ),
            actions: [
              TertiaryButton(
                label: 'Not now',
                onPressed: () => Navigator.pop(context, false),
              ),
              PrimaryButton(
                label: 'Plan a trip',
                onPressed: () => Navigator.pop(context, true),
              ),
            ],
          ),
        );
        if (plan == true && mounted) {
          await open(
            PersonalizedPlanningScreen(api: widget.api),
            refreshCoreOnReturn: true,
          );
        }
        return;
      }

      final selected = await showModalBottomSheet<Map<String, dynamic>>(
        context: context,
        showDragHandle: true,
        builder: (context) => SafeArea(
          child: ListView(
            shrinkWrap: true,
            padding: const EdgeInsets.fromLTRB(
              AppSpacing.md,
              0,
              AppSpacing.md,
              AppSpacing.xl,
            ),
            children: [
              Text(
                'Add to trip',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: AppSpacing.xs),
              ...available.map((raw) {
                final trip = Map<String, dynamic>.from(raw);
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(Icons.luggage_outlined),
                  ),
                  title: Text((trip['title'] ?? 'Trip').toString()),
                  subtitle: Text((trip['destinationArea'] ?? '').toString()),
                  onTap: () => Navigator.pop(context, trip),
                );
              }),
            ],
          ),
        ),
      );
      if (selected == null) return;
      await api.post('/api/fr5/itineraries/${selected['id']}/activities', {
        'activityName': (item['title'] ?? item['name'] ?? 'Place').toString(),
        'destinationId': destinationId(item),
        'address': item['address'] ?? '',
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'indoor': item['indoor'] ?? false,
        'openingHours': item['openingHours'] ?? '',
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
        'dayNo': 1,
      });
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added to ${selected['title'] ?? 'trip'}')),
        );
      }
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }


  bool _isPackagePromoActive(Map<String, dynamic> item) {
    final promo = item['promotionalPrice'];
    final promoNum = promo is num ? promo : num.tryParse(promo?.toString() ?? '');
    if (promoNum == null || promoNum <= 0) return false;
    final regular = item['adultPrice'] ?? item['price'];
    final regularNum = regular is num ? regular : num.tryParse(regular?.toString() ?? '');
    if (regularNum != null && promoNum >= regularNum) return false;

    final startStr = item['promotionStart']?.toString().trim();
    final endStr = item['promotionEnd']?.toString().trim();
    if ((startStr == null || startStr.isEmpty) && (endStr == null || endStr.isEmpty)) {
      return false;
    }

    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    if (startStr != null && startStr.isNotEmpty) {
      final start = DateTime.tryParse(startStr);
      if (start != null) {
        final startDate = DateTime(start.year, start.month, start.day);
        if (today.isBefore(startDate)) return false;
      }
    }
    if (endStr != null && endStr.isNotEmpty) {
      final end = DateTime.tryParse(endStr);
      if (end != null) {
        final endDate = DateTime(end.year, end.month, end.day);
        if (today.isAfter(endDate)) return false;
      }
    }
    return true;
  }

  String _packagePrice(Map<String, dynamic> item) {
    final value = _isPackagePromoActive(item)
        ? (item['promotionalPrice'] ?? item['adultPrice'] ?? item['price'])
        : (item['adultPrice'] ?? item['price']);
    final amount = value is num ? value : num.tryParse(value?.toString() ?? '');
    if (amount == null) return '';
    final currency = (item['currency'] ?? 'MYR').toString();
    final formatted = amount == amount.roundToDouble()
        ? amount.toStringAsFixed(0)
        : amount.toStringAsFixed(2);
    final basis = item['priceBasis'] == 'per_group' ? 'group' : 'person';
    return '$currency $formatted / $basis';
  }

  String _packageDuration(Map<String, dynamic> item) {
    final days = int.tryParse((item['durationDays'] ?? '').toString());
    if (days == null || days < 1) return '';
    final nights = int.tryParse((item['durationNights'] ?? '').toString());
    final dayText = '$days ${days == 1 ? 'day' : 'days'}';
    return nights == null
        ? dayText
        : '$dayText · $nights ${nights == 1 ? 'night' : 'nights'}';
  }

  Widget _profileCard() {
    if (loadingCore && preferences == null) {
      return const _SectionLoading(message: 'Loading your travel style…');
    }
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                width: 40,
                height: 40,
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: AppRadii.control,
                ),
                child: const Icon(
                  Icons.explore_outlined,
                  size: 20,
                  color: AppColors.primaryStrong,
                ),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      'Your travel style',
                      style: Theme.of(context)
                          .textTheme
                          .labelMedium
                          ?.copyWith(color: AppColors.textSecondary),
                    ),
                    const SizedBox(height: 1),
                    Text(
                      travelPersonality,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                    Text(
                      preferenceSummary,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textSecondary,
                          ),
                    ),
                  ],
                ),
              ),
              TertiaryButton(
                label: 'Adjust',
                onPressed: () => open(
                  const PreferencesScreen(),
                  refreshCoreOnReturn: true,
                ),
              ),
            ],
          ),
          if (interests.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.xs),
            Wrap(
              spacing: AppSpacing.xs,
              runSpacing: AppSpacing.xxs,
              children: interests
                  .take(4)
                  .map(
                    (interest) => StatusChip(
                      text: interest,
                      tone: AppStatusTone.neutral,
                    ),
                  )
                  .toList(),
            ),
          ],
        ],
      ),
    );
  }

  Widget _planningCard() {
    return InkCard(
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.center,
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.auto_awesome_rounded,
                      size: 16,
                      color: AppColors.primaryStrong,
                    ),
                    const SizedBox(width: AppSpacing.xxs),
                    Text(
                      'Plan your next trip',
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.w700,
                          ),
                    ),
                  ],
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  'Turn your preferences into a personalised itinerary and budget.',
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
                const SizedBox(height: AppSpacing.sm),
                PrimaryButton(
                  label: 'Plan a trip',
                  icon: Icons.add_rounded,
                  onPressed: () => open(
                    PersonalizedPlanningScreen(api: widget.api),
                    refreshCoreOnReturn: true,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _forYouSection() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSectionHeader(
          title: 'For you',
          subtitle: 'Places selected from your travel style',
          actionLabel: recommendations.isEmpty ? null : 'See all',
          onAction: recommendations.isEmpty
              ? null
              : () => open(RecommendationScreen(api: widget.api)),
        ),
        const SizedBox(height: AppSpacing.xs),
        Align(
          alignment: Alignment.centerLeft,
          child: TertiaryButton(
            label: loadingForYou ? 'Refreshing…' : 'Refresh recommendations',
            icon: Icons.refresh_rounded,
            onPressed: loadingForYou
                ? null
                : () => loadRecommendations(regenerate: true),
          ),
        ),
        if (recommendationError != null && recommendations.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.xs),
          _InlineNotice(
            message: recommendationError!,
            onRetry: () => loadRecommendations(regenerate: true),
          ),
        ],
        const SizedBox(height: AppSpacing.xs),
        if (loadingForYou && recommendations.isEmpty)
          const _SectionLoading(message: 'Finding places for you…')
        else if (recommendationError != null && recommendations.isEmpty)
          AppErrorState(
            message: recommendationError!,
            onRetry: () => loadRecommendations(regenerate: true),
          )
        else if (recommendations.isEmpty)
          TravelEmptyState(
            icon: Icons.auto_awesome_outlined,
            title: 'No recommendations yet',
            message:
                'Refresh after setting your travel style to find places matched to you.',
            actionLabel: 'Adjust preferences',
            onAction: () => open(
              const PreferencesScreen(),
              refreshCoreOnReturn: true,
            ),
          )
        else
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: recommendations.take(4).map((raw) {
                final item = Map<String, dynamic>.from(raw as Map);
                return Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: SizedBox(
                    width: math.min(
                      MediaQuery.sizeOf(context).width * .76,
                      280,
                    ),
                    child: RecommendationCard(
                      recommendation: item,
                      source: recommendationSource,
                      preferenceFeedback:
                          feedbackByDestination[destinationId(item)],
                      feedbackBusy:
                          feedbackInFlight.contains(destinationId(item)),
                      onPreferenceFeedback: (value) =>
                          submitPreferenceFeedback(item, value),
                      onView: () => open(
                        DestinationDetailsScreen(
                          initialDestination: item,
                          api: widget.api,
                        ),
                      ),
                      onAddToTrip: () => addToTrip(item),
                    ),
                  ),
                );
              }).toList(),
            ),
          ),
      ],
    );
  }

  Widget _continuePlanningSection(Map<String, dynamic>? trip) {
    if (trip == null) return const SizedBox.shrink();
    final isPackage = trip['tripType'] == 'package' || trip['packageTrip'] == true;
    final activities = trip['activities'] as List? ?? [];
    final budget = _budgetSummary(trip);
    final status = (trip['status'] ?? 'draft').toString();
    final tone = isPackage
        ? AppStatusTone.success
        : status == 'generation_failed'
            ? AppStatusTone.error
            : status == 'planned'
                ? AppStatusTone.success
                : AppStatusTone.info;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSectionHeader(
          title: isPackage ? 'Your package trip' : 'Continue planning',
          subtitle: isPackage
              ? 'View your verified operator itinerary'
              : 'Pick up your latest travel plan',
          actionLabel: 'All trips',
          onAction: openTripsTab,
        ),
        const SizedBox(height: AppSpacing.sm),
        InkWell(
          key: ValueKey('continue-trip-${trip['id']}'),
          borderRadius: AppRadii.card,
          onTap: () => open(
            isPackage
                ? PackageTripDetailsScreen(
                    key: ValueKey('continue-package-${trip['id']}'),
                    tripId: trip['id'].toString(),
                    api: api,
                    initialTrip: trip,
                  )
                : TripDetailsScreen(tripId: trip['id'].toString(), api: api),
            refreshCoreOnReturn: true,
          ),
          child: InkCard(
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 54,
                  height: 54,
                  decoration: BoxDecoration(
                    color: isPackage ? AppColors.successSoft : AppColors.primarySoft,
                    borderRadius: AppRadii.control,
                  ),
                  child: Icon(
                    isPackage ? Icons.verified_rounded : Icons.route_rounded,
                    color: isPackage ? AppColors.success : AppColors.primaryStrong,
                  ),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Expanded(
                            child: Text(
                              (trip['title'] ?? 'My trip').toString(),
                              style: Theme.of(context).textTheme.titleLarge,
                            ),
                          ),
                          StatusChip(
                            text: isPackage ? 'Purchased Package' : status.replaceAll('_', ' '),
                            tone: tone,
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.xxs),
                      Text(
                        (trip['destinationArea'] ?? '').toString(),
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                      const SizedBox(height: AppSpacing.xs),
                      Text(
                        isPackage
                            ? '${_tripDays(trip)} days · Official operator itinerary'
                            : '${_tripDays(trip)} days · ${activities.length} activities',
                        style: Theme.of(context).textTheme.labelMedium,
                      ),
                      if (budget != null) ...[
                        const SizedBox(height: AppSpacing.xxs),
                        Text(
                          isPackage
                              ? 'RM ${trip['paidTotal'] ?? 0} paid'
                              : budget,
                          style:
                              Theme.of(context).textTheme.bodySmall?.copyWith(
                                    color: AppColors.textSecondary,
                                  ),
                        ),
                      ],
                    ],
                  ),
                ),
                const Padding(
                  padding: EdgeInsets.only(top: AppSpacing.sm),
                  child: Icon(Icons.chevron_right_rounded),
                ),
              ],
            ),
          ),
        ),
      ],
    );
  }

  Widget _inspirationSection() {
    final visibleInterests = interests.take(5).toList();
    if (visibleInterests.isEmpty && tourismPackages.isEmpty) {
      return const SizedBox.shrink();
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppSectionHeader(
          title: 'Travel inspiration',
          subtitle: 'Explore ideas that fit your interests',
        ),
        if (visibleInterests.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.sm),
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: visibleInterests
                .map(
                  (interest) => ActionChip(
                    avatar: const Icon(Icons.explore_outlined, size: 18),
                    label: Text(interest),
                    onPressed: () => open(
                      ExploreTab(
                        initialQuery: interest,
                        initialLocation: 'Malaysia',
                      ),
                    ),
                  ),
                )
                .toList(),
          ),
        ],
        if (loadingSharedContent && tourismPackages.isEmpty) ...[
          const SizedBox(height: AppSpacing.sm),
          const _SectionLoading(message: 'Loading travel inspiration…'),
        ] else if (tourismPackages.isNotEmpty) ...[
          const SizedBox(height: AppSpacing.md),
          SingleChildScrollView(
            scrollDirection: Axis.horizontal,
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: tourismPackages.take(4).map((raw) {
                final item = Map<String, dynamic>.from(raw as Map);
                return Padding(
                  padding: const EdgeInsets.only(right: AppSpacing.sm),
                  child: SizedBox(width: 285, child: _packageCard(item)),
                );
              }).toList(),
            ),
          ),
        ],
      ],
    );
  }

  Widget _packageCard(Map<String, dynamic> item) {
    final title =
        (item['title'] ?? item['packageTitle'] ?? 'Travel package').toString();
    final destination =
        (item['destination'] ?? item['destinationName'] ?? '').toString();
    final price = _packagePrice(item);
    final duration = _packageDuration(item);
    return InkWell(
      borderRadius: AppRadii.card,
      onTap: () => open(
        TourismPackageDetailsScreen(
          item: item,
          api: api,
        ),
      ),
      child: InkCard(
        padding: EdgeInsets.zero,
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TravelPlaceImage(
            place: {
              'title': title,
              'imageUrl': item['heroImage'] ??
                  item['imageUrl'] ??
                  item['bannerImageUrl'] ??
                  '',
              'category': 'Travel package',
            },
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
                Text(
                  title,
                  maxLines: 2,
                  overflow: TextOverflow.ellipsis,
                  style: Theme.of(context).textTheme.titleMedium,
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  destination,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
                if (duration.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xxs),
                  Text(duration,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textSecondary,
                          )),
                ],
                if (price.isNotEmpty) ...[
                  const SizedBox(height: AppSpacing.xs),
                  Text(price, style: Theme.of(context).textTheme.titleMedium),
                ],
                if ((item['operatorName'] ?? '').toString().trim().isNotEmpty)
                  Text('by ${item['operatorName']}',
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textSecondary,
                          )),
                const SizedBox(height: AppSpacing.sm),
                SizedBox(
                  width: double.infinity,
                  child: PrimaryButton(
                    key: ValueKey('package-view-btn-${item['id'] ?? title}'),
                    label: 'View Package',
                    icon: Icons.arrow_forward_rounded,
                    onPressed: () => open(
                      TourismPackageDetailsScreen(
                        item: item,
                        api: api,
                      ),
                    ),
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

  Widget _toolsSection() {
    final activeDestination = (continuationTrip?['destinationArea'] ?? '').toString().trim();
    final activeStartDate = (continuationTrip?['startDate'] ?? '').toString().trim();
    final activeEndDate = (continuationTrip?['endDate'] ?? '').toString().trim();
    final tools = <(IconData, String, Widget)>[
      (Icons.flight_takeoff_rounded, 'Flights', const FlightScreen()),
      (Icons.hotel_rounded, 'Hotels', HotelScreen(
        initialDestination: activeDestination.isNotEmpty ? activeDestination : null,
        initialCheckin: activeStartDate.isNotEmpty ? activeStartDate : null,
        initialCheckout: activeEndDate.isNotEmpty ? activeEndDate : null,
      )),
      (Icons.directions_car_outlined, 'Car rentals', CarRentalScreen(
        initialPickupLocation: activeDestination.isNotEmpty ? activeDestination : null,
        initialPickupDate: activeStartDate.isNotEmpty ? activeStartDate : null,
        initialDropoffDate: activeEndDate.isNotEmpty ? activeEndDate : null,
      )),
      (Icons.cloud_outlined, 'Weather', const WeatherScreen()),
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppSectionHeader(
          title: 'Travel tools',
          subtitle: 'Helpful details when you need them',
        ),
        const SizedBox(height: AppSpacing.sm),
        Row(
          children: tools.map((tool) {
            return Expanded(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: AppSpacing.xxs),
                child: InkWell(
                  onTap: () => open(tool.$3),
                  borderRadius: AppRadii.control,
                  child: Container(
                    padding: const EdgeInsets.symmetric(
                      vertical: AppSpacing.sm,
                      horizontal: AppSpacing.xxs,
                    ),
                    decoration: BoxDecoration(
                      color: AppColors.surface,
                      borderRadius: AppRadii.control,
                      border: Border.all(color: AppColors.divider),
                    ),
                    child: Column(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        Icon(tool.$1, size: 22, color: AppColors.primary),
                        const SizedBox(height: AppSpacing.xxs),
                        Text(
                          tool.$2,
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: Theme.of(context).textTheme.labelSmall?.copyWith(
                                fontWeight: FontWeight.w600,
                              ),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            );
          }).toList(),
        ),
      ],
    );
  }

  Widget _offersSection() {
    if (promotionalCampaigns.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppSectionHeader(
          title: 'Special offers',
          subtitle: 'Optional savings for your travel plans',
        ),
        const SizedBox(height: AppSpacing.sm),
        ...promotionalCampaigns.take(3).map((raw) {
          final item = Map<String, dynamic>.from(raw as Map);
          return Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.xs),
            child: InkWell(
              borderRadius: AppRadii.card,
              onTap: () => open(CampaignDetailsScreen(item: item)),
              child: InkCard(
                color: InkWashColors.cream,
                child: Row(
                  children: [
                    const Icon(
                      Icons.local_offer_outlined,
                      color: AppColors.primaryStrong,
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            (item['campaignTitle'] ?? 'Travel offer')
                                .toString(),
                            maxLines: 2,
                            overflow: TextOverflow.ellipsis,
                            style: Theme.of(context).textTheme.titleMedium,
                          ),
                          if ((item['packageTitle'] ?? '')
                              .toString()
                              .isNotEmpty)
                            Text(
                              item['packageTitle'].toString(),
                              style: Theme.of(context)
                                  .textTheme
                                  .bodySmall
                                  ?.copyWith(color: AppColors.textSecondary),
                            ),
                        ],
                      ),
                    ),
                    const Icon(Icons.chevron_right_rounded),
                  ],
                ),
              ),
            ),
          );
        }),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final trip = continuationTrip;
    return Scaffold(
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: refreshHome,
          child: ListView(
            padding: AppSpacing.page,
            children: [
              Row(
                children: [
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '$greeting, $firstName',
                          style: Theme.of(context).textTheme.headlineLarge,
                        ),
                        const SizedBox(height: AppSpacing.xxs),
                        Text(
                          'Where would you like to go next?',
                          style:
                              Theme.of(context).textTheme.bodyLarge?.copyWith(
                                    color: AppColors.textSecondary,
                                  ),
                        ),
                      ],
                    ),
                  ),
                  CircleAvatar(
                    radius: 23,
                    backgroundColor: InkWashColors.cream,
                    child: Text(
                      firstName.characters.first.toUpperCase(),
                      style: Theme.of(context).textTheme.titleMedium,
                    ),
                  ),
                ],
              ),
              if (coreError != null) ...[
                const SizedBox(height: AppSpacing.sm),
                _InlineNotice(message: coreError!, onRetry: _loadCoreData),
              ],
              const SizedBox(height: AppSpacing.lg),
              _profileCard(),
              const SizedBox(height: AppSpacing.md),
              _planningCard(),
              const SizedBox(height: AppSpacing.md),
              SearchField(
                controller: searchController,
                hint: 'Search places, food, culture or nature',
                onSubmitted: (value) => open(
                  ExploreTab(
                    initialQuery:
                        value.trim().isEmpty ? 'attractions' : value.trim(),
                    initialLocation: 'Malaysia',
                  ),
                ),
                onClear: () => searchController.clear(),
              ),
              const SizedBox(height: AppSpacing.md),
              _forYouSection(),
              if (trip != null) ...[
                const SizedBox(height: AppSpacing.lg),
                _continuePlanningSection(trip),
              ],
              const SizedBox(height: AppSpacing.lg),
              _toolsSection(),
              if (interests.isNotEmpty ||
                  tourismPackages.isNotEmpty ||
                  loadingSharedContent) ...[
                const SizedBox(height: AppSpacing.lg),
                _inspirationSection(),
              ],
              if (promotionalCampaigns.isNotEmpty) ...[
                const SizedBox(height: AppSpacing.lg),
                _offersSection(),
              ],
              const SizedBox(height: AppSpacing.lg),
            ],
          ),
        ),
      ),
    );
  }
}

class _LoadResult {
  final dynamic data;
  final Object? error;

  const _LoadResult({this.data, this.error});
}

class _SectionLoading extends StatelessWidget {
  final String message;

  const _SectionLoading({required this.message});

  @override
  Widget build(BuildContext context) {
    return InkCard(
      child: Row(
        children: [
          const SizedBox.square(
            dimension: AppSizes.icon,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(child: Text(message)),
        ],
      ),
    );
  }
}

class _InlineNotice extends StatelessWidget {
  final String message;
  final VoidCallback onRetry;

  const _InlineNotice({required this.message, required this.onRetry});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: AppSpacing.card,
      decoration: BoxDecoration(
        color: AppColors.warningSoft,
        borderRadius: AppRadii.control,
      ),
      child: Row(
        children: [
          const Icon(Icons.info_outline_rounded, color: AppColors.warning),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Text(message, style: Theme.of(context).textTheme.bodySmall),
          ),
          TertiaryButton(label: 'Retry', onPressed: onRetry),
        ],
      ),
    );
  }
}
