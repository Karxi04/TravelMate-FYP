import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../core/utils/recommendation_page.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/recommendation_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr02_travel_preference/preferences_screen.dart';

class RecommendationScreen extends StatefulWidget {
  final String initialDestination;
  final ApiService? api;

  const RecommendationScreen({
    super.key,
    this.initialDestination = 'Malaysia',
    this.api,
  });

  @override
  State<RecommendationScreen> createState() => _RecommendationScreenState();
}

class _RecommendationScreenState extends State<RecommendationScreen> {
  late final ApiService api;
  late final TextEditingController destination;
  List<dynamic> items = [];
  bool busy = true;
  String source = '';
  Map<String, dynamic> preferences = {};
  Map<String, String> feedbackByDestination = {};
  final Set<String> feedbackInFlight = {};
  String recommendationGenerationId = '';
  String? errorMessage;
  double minimumMatch = 70;
  Map<String, dynamic> pagination = {};
  int requestVersion = 0;
  String generatedDestination = '';
  bool loadingMore = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    destination = TextEditingController(text: widget.initialDestination);
    Future.microtask(loadExisting);
  }

  @override
  void dispose() {
    destination.dispose();
    super.dispose();
  }

  String _errorText(Object error) =>
      error.toString().replaceFirst('Exception: ', '');

  Future<void> loadExisting() async {
    final version = ++requestVersion;
    if (mounted) {
      setState(() {
        busy = true;
        errorMessage = null;
      });
    }

    Object? recommendationError;
    bool stale = false;
    try {
      final settings = await api.get('/api/fr4/settings');
      final value = double.tryParse('${settings['minimumMatchScore']}');
      if (mounted && version == requestVersion && value != null && value >= 40 && value <= 90) setState(() => minimumMatch = value);
    } catch (_) { /* The initial testing default remains 70 when settings cannot load. */ }
    try {
      final data = await api.get('/api/fr4/recommendations', {'minimumMatchScore':'$minimumMatch'});
      if (mounted && version == requestVersion && data is Map) {
        stale = data['stale'] == true;
        setState(() {
          items = data['recommendations'] as List? ?? [];
          source = (data['source'] ?? '').toString();
          pagination = Map<String, dynamic>.from(data['pagination'] as Map? ?? {});
          generatedDestination = (data['snapshot']?['requestedDestination'] ?? widget.initialDestination).toString();
          destination.text = generatedDestination;
          recommendationGenerationId = (data['recommendationGenerationId'] ??
                  data['snapshot']?['recommendationGenerationId'] ??
                  '')
              .toString();
        });
      }
    } catch (error) {
      recommendationError = error;
    }

    try {
      final prefData = await api.get('/api/fr2/preferences');
      if (mounted && version == requestVersion && prefData is Map && prefData['preferences'] is Map) {
        setState(() {
          preferences = Map<String, dynamic>.from(
            prefData['preferences'] as Map,
          );
        });
      }
    } catch (_) {
      // Recommendations remain useful when the compact profile summary fails.
    }

    try {
      final learning = await api.get('/api/fr4/preference-feedback');
      if (mounted && version == requestVersion && learning is Map && learning['learning'] is Map) {
        final current = Map<String, dynamic>.from(
          learning['learning']['currentFeedback'] as Map? ?? const {},
        );
        setState(() {
          feedbackByDestination = current.map(
            (key, value) => MapEntry(key, value.toString()),
          );
        });
      }
    } catch (_) {
      // Feedback controls remain optional if preference learning is unavailable.
    }

    if (!mounted || version != requestVersion) return;
    setState(() {
      busy = false;
      if (recommendationError != null) {
        errorMessage = _errorText(recommendationError);
      }
    });
    if (recommendationError == null && (stale || recommendationGenerationId.isEmpty) && preferences.isNotEmpty) await generate(reuseCandidates:stale);
  }

  Future<void> generate({bool reuseCandidates = false, bool expand = false}) async {
    final version = ++requestVersion;
    final requestedArea = destination.text.trim();
    if (requestedArea.isEmpty) {
      setState(() => errorMessage = 'Enter a destination area first.');
      return;
    }

    setState(() {
      busy = true;
      loadingMore = false;
      errorMessage = null;
    });
    try {
      final data = await api.post('/api/fr4/recommendations/generate', {
        'destinationArea': requestedArea,
        'minimumMatchScore': minimumMatch,
        if ((reuseCandidates || expand) && generatedDestination == requestedArea && recommendationGenerationId.isNotEmpty)
          'previousGenerationId': recommendationGenerationId,
        if (expand) 'expandCandidates': true,
      });
      if (!mounted || version != requestVersion || data is! Map) return;
      setState(() {
        items = data['recommendations'] as List? ?? [];
        source = (data['source'] ?? '').toString();
        pagination = Map<String, dynamic>.from(data['pagination'] as Map? ?? {});
        generatedDestination = requestedArea;
        recommendationGenerationId = (data['recommendationGenerationId'] ??
                data['snapshot']?['recommendationGenerationId'] ??
                '')
            .toString();
      });
    } catch (error) {
      if (mounted && version == requestVersion) setState(() => errorMessage = _errorText(error));
    } finally {
      if (mounted && version == requestVersion) setState(() => busy = false);
    }
  }

  Future<void> loadPage({bool reset = false}) async {
    if (loadingMore || recommendationGenerationId.isEmpty) return;
    final version = ++requestVersion;
    setState(() { loadingMore = true; errorMessage = null; });
    try {
      final data = await api.get('/api/fr4/recommendations', {
        'generationId': recommendationGenerationId, 'minimumMatchScore':'$minimumMatch',
        'offset': reset ? '0' : '${pagination['nextOffset'] ?? 0}',
      });
      if (!mounted || version != requestVersion) return;
      if (data['stale'] == true) { await generate(reuseCandidates:true); return; }
      setState(() {
        final received = data['recommendations'] as List? ?? [];
        final seen = reset ? <String>{} : items.whereType<Map>().map((item) => _destinationId(Map<String,dynamic>.from(item))).toSet();
        items = [if (!reset) ...items, ...received.whereType<Map>().where((item) => seen.add(_destinationId(Map<String,dynamic>.from(item))))];
        pagination = Map<String,dynamic>.from(data['pagination'] as Map? ?? {});
      });
    } catch (error) {
      if (mounted && version == requestVersion) setState(() => errorMessage = _errorText(error));
    } finally {
      if (mounted && version == requestVersion) setState(() => loadingMore = false);
    }
  }

  Future<void> changeThreshold(double value) async {
    ++requestVersion;
    setState(() { minimumMatch = value; loadingMore = false; });
    try { await api.put('/api/fr4/settings', {'minimumMatchScore':value}); }
    catch (error) { if (mounted) showError(context, 'Minimum match could not be saved: ${_errorText(error)}'); }
    if (!mounted) return;
    if (recommendationGenerationId.isNotEmpty) await loadPage(reset:true);
    else await generate();
  }

  String _destinationId(Map<String, dynamic> item) => (item['destinationId'] ??
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
    final id = _destinationId(item);
    if (id.isEmpty || feedbackInFlight.isNotEmpty) return;
    ++requestVersion;
    setState(() => feedbackInFlight.add(id));
    try {
      final data = await api.post('/api/fr4/preference-feedback', {
        'destinationId': id,
        'recommendationGenerationId': recommendationGenerationId,
        'feedbackType': feedbackType,
        'sourceContext': 'for_you',
        if (recommendationGenerationId.isEmpty)
          'destinationConcepts': item['destinationConcepts'],
      });
      if (data is Map && data['ok'] == false) {
        throw Exception(data['error'] ?? 'Feedback could not be saved.');
      }
      if (!mounted) return;
      setState(() => feedbackByDestination[id] = feedbackType);
      await generate(reuseCandidates:true);
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

  Future<void> addToItinerary(Map<String, dynamic> item) async {
    try {
      final data = await api.get('/api/fr5/itineraries');
      final trips = data['items'] as List? ?? [];
      if (!mounted) return;
      if (trips.isEmpty) {
        showError(context, 'Plan a trip before adding this recommendation.');
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
              AppSpacing.lg,
            ),
            children: [
              Text(
                'Add to trip',
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              const SizedBox(height: AppSpacing.xs),
              ...trips.map((raw) {
                final trip = Map<String, dynamic>.from(raw as Map);
                return ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: InkWashColors.cream,
                    child: Icon(
                      Icons.luggage_outlined,
                      color: InkWashColors.blueGrey,
                    ),
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
        'activityName':
            (item['title'] ?? item['name'] ?? 'Destination').toString(),
        'destinationId':
            (item['destinationId'] ?? item['place_id'] ?? '').toString(),
        'address': item['address'] ?? '',
        'dayNo': 1,
        'estimatedCost': item['estimatedCost'] ?? 0,
        'gps_coordinates':
            item['gps_coordinates'] ?? item['gpsCoordinates'] ?? {},
        'type': item['type'] ?? item['category'] ?? '',
        'category': item['category'] ?? item['type'] ?? '',
        'description': item['description'] ?? '',
        'openingHours': item['openingHours'] ?? '',
        'indoor': item['indoor'] ?? false,
        'recommendedDurationMinutes': item['recommendedDurationMinutes'] ?? 90,
        for (final key in const [
          'thumbnail',
          'image',
          'imageUrl',
          'mainPhoto',
          'main_photo',
          'photo',
          'photos',
          'images',
          'heroImage',
          'galleryImages',
        ])
          if (item[key] != null) key: item[key],
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

  List<String> get interests => (preferences['interests'] as List? ?? [])
      .map((value) => value.toString())
      .where((value) => value.trim().isNotEmpty)
      .toList();

  Widget _profileSummary() {
    if (preferences.isEmpty) return const SizedBox.shrink();
    final personality = (preferences['travelPersonality'] ??
            preferences['travelType'] ??
            'Your travel style')
        .toString();
    final pace = (preferences['travelPace'] ?? '').toString();
    return InkCard(
      color: InkWashColors.cream,
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(
            Icons.explore_outlined,
            color: AppColors.primaryStrong,
            semanticLabel: 'Travel style',
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(personality,
                    style: Theme.of(context).textTheme.titleLarge),
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  [
                    ...interests.take(3),
                    if (pace.trim().isNotEmpty) '$pace pace',
                  ].join(' · '),
                  style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                        color: AppColors.textSecondary,
                      ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final qualified = items.whereType<Map>().where((item) => recommendationQualifies(item,minimumMatch)).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('For you')),
      body: RefreshIndicator(
        onRefresh: generate,
        child: ListView(
          padding: AppSpacing.page,
          children: [
            const AppSectionHeader(
              title: 'Places recommended for you',
              subtitle:
                  'Based on your saved interests and travel style. Refresh only when you want a new list.',
            ),
            if (preferences.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.md),
              _profileSummary(),
            ],
            const SizedBox(height: AppSpacing.md),
            AppTextField(
              controller: destination,
              label: 'Destination area',
              hint: 'e.g. Penang, Malaysia',
              prefixIcon: Icons.location_on_outlined,
              onChanged: (value) {
                if (value.trim() != generatedDestination) {
                  ++requestVersion;
                  setState(() { items=[]; pagination={}; recommendationGenerationId=''; busy=false; loadingMore=false; });
                }
              },
              textInputAction: TextInputAction.search,
              onSubmitted: (_) => busy ? null : generate(),
            ),
            const SizedBox(height: AppSpacing.sm),
            Text('Minimum match: ${minimumMatch.round()}/100'),
            Slider(value: minimumMatch, min:40, max:90, divisions:10,
              label:'${minimumMatch.round()}/100',
              onChanged: busy ? null : (value) => setState(() => minimumMatch = value),
              onChangeEnd: changeThreshold),
            TertiaryButton(label:'Change preferences', onPressed: () async {
              await Navigator.push(context, MaterialPageRoute(builder: (_) => PreferencesScreen(api:widget.api)));
              if (mounted) await loadExisting();
            }),
            PrimaryButton(
              label: busy ? 'Refreshing recommendations' : 'Refresh for you',
              icon: Icons.auto_awesome_rounded,
              loading: busy,
              onPressed: generate,
            ),
            if (errorMessage != null && items.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.sm),
              Container(
                padding: AppSpacing.card,
                decoration: BoxDecoration(
                  color: AppColors.warningSoft,
                  borderRadius: AppRadii.control,
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.info_outline_rounded,
                      color: AppColors.warning,
                    ),
                    const SizedBox(width: AppSpacing.sm),
                    Expanded(child: Text(errorMessage!)),
                    TertiaryButton(label: 'Retry', onPressed: generate),
                  ],
                ),
              ),
            ],
            const SizedBox(height: AppSpacing.xl),
            if (busy && qualified.isEmpty)
              const AppLoadingState(message: 'Loading recommendations…')
            else if (errorMessage != null && qualified.isEmpty)
              AppErrorState(message: errorMessage!, onRetry: loadExisting)
            else if (qualified.isEmpty)
              TravelEmptyState(
                icon: Icons.auto_awesome_outlined,
                title: 'No places meet this minimum match',
                message:
                    'No available destinations meet ${minimumMatch.round()}/100. Lower the minimum explicitly, change preferences, or search another Malaysian destination.',
                actionLabel: minimumMatch > 40 ? 'Lower minimum match' : 'Refresh for you',
                onAction: minimumMatch > 40 ? () => changeThreshold((minimumMatch - 10).clamp(40,90)) : generate,
              )
            else
              ...qualified.map((raw) {
                final item = Map<String, dynamic>.from(raw);
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.md),
                  child: RecommendationCard(
                    recommendation: item,
                    source: source,
                    preferenceFeedback:
                        feedbackByDestination[_destinationId(item)],
                    feedbackBusy:
                        feedbackInFlight.contains(_destinationId(item)),
                    onPreferenceFeedback: (value) =>
                        submitPreferenceFeedback(item, value),
                    onView: () => Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => DestinationDetailsScreen(
                          initialDestination: item,
                          api: widget.api,
                        ),
                      ),
                    ),
                    onAddToTrip: () => addToItinerary(item),
                  ),
                );
              }),
            if (pagination['hasMore'] == true)
              PrimaryButton(label:'Load more matching places', loading:loadingMore, onPressed:() => loadPage()),
            if (pagination['hasMore'] != true && pagination['providerHasMore'] == true)
              PrimaryButton(label:'Discover more places', loading:busy, onPressed:() => generate(expand:true)),
          ],
        ),
      ),
    );
  }
}
