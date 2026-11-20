import '../fr05_smart_itinerary_budget_planner/activity_payload_helper.dart';
import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

import '../../services/api_service.dart';
import '../../core/utils/recommendation_page.dart';
import '../../core/utils/malaysian_locations.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/recommendation_card.dart';
import '../../widgets/local_place_rating.dart';
import '../../widgets/travel_widgets.dart';
import '../fr03_destination_search_information/destination_details_screen.dart';
import '../fr02_travel_preference/preferences_screen.dart';
import 'demonstration_recommendations_screen.dart';

class RecommendationScreen extends StatefulWidget {
  final String initialDestination;
  final String initialGenerationId;
  final ApiService? api;

  const RecommendationScreen({
    super.key,
    this.initialDestination = 'Malaysia',
    this.initialGenerationId = '',
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
  Map<String, dynamic> pagination = {};
  int requestVersion = 0;
  String generatedDestination = '';
  String? discoveryNotice;
  bool loadingMore = false;
  bool generationInFlight = false;
  int destinationSelection = 0, locationLookupVersion = 0;
  bool locationsLoading = true, locationLookupBusy = false;
  String? locationNotice;
  List<Map<String, dynamic>> lookupMatches = [];
  Map<String, dynamic> generatedScope = {};
  String geographicMode = 'strict';
  bool nearbyAvailable = false;
  bool demonstrationAvailable = false;
  List<Map<String, dynamic>> locations = [];
  Map<String, dynamic>? selectedLocation;
  String? searchMessage;
  String? coverageNotice;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    destination = TextEditingController(text: widget.initialDestination);
    recommendationGenerationId = widget.initialGenerationId;
    Future.microtask(loadExisting);
    Future.microtask(() async {
      try {
        final data = await api.get('/api/fr4/locations');
        if (mounted) setState(() => locations = (data['locations'] as List? ?? []).whereType<Map>().map((row) => Map<String, dynamic>.from(row)).toList());
      } catch (_) {
        if (mounted) setState(() => locationNotice = 'Location suggestions are unavailable. You can still enter a supported Malaysian area.');
      } finally {
        if (mounted) setState(() => locationsLoading = false);
      }
    });
  }

  @override
  void dispose() {
    destination.dispose();
    super.dispose();
  }

  String _errorText(Object error) => error is ApiException &&
      {'destination_provider_unavailable', 'discovery_unavailable'}.contains(error.code)
      ? error.message : userFacingApiError(error);

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
      final data = await api.get('/api/fr4/recommendations', {'discoveryMode':recommendationDiscoveryMode,
        if (recommendationGenerationId.isNotEmpty || destination.text != 'Malaysia') 'destinationArea':destination.text,
        if (recommendationGenerationId.isNotEmpty) 'generationId':recommendationGenerationId});
      if (mounted && version == requestVersion && data is Map) {
        validateDiscoveryResponse(data);
        stale = data['stale'] == true;
        setState(() {
          items = data['recommendations'] as List? ?? [];
          demonstrationAvailable = data['demonstrationAvailable'] == true;
          source = (data['source'] ?? '').toString();
          pagination = Map<String, dynamic>.from(data['pagination'] as Map? ?? {});
          discoveryNotice = data['snapshot']?['cacheFallbackNotice']?.toString();
          searchMessage = data['snapshot']?['searchMessage']?.toString();
          coverageNotice = data['snapshot']?['coverageNotice']?.toString();
          nearbyAvailable = data['snapshot']?['nearbyAvailable'] == true;
          generatedScope = Map<String, dynamic>.from(data['snapshot']?['canonicalDestinationScope'] as Map? ?? {});
          geographicMode = generatedScope['geographicMode'] == 'nearby' ? 'nearby' : 'strict';
          if (generatedScope['locationId'] != null) selectedLocation = {...generatedScope,
            if (geographicMode == 'nearby') 'scopeKey': generatedScope['originScopeKey']};
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
    if (busy || loadingMore || generationInFlight) return;
    final version = ++requestVersion;
    final requestedArea = destination.text.trim();
    if (requestedArea.isEmpty) {
      setState(() => errorMessage = 'Enter a destination area first.');
      return;
    }

    setState(() {
      generationInFlight = true;
      busy = true;
      loadingMore = false;
      errorMessage = null;
    });
    try {
      final data = await api.post('/api/fr4/recommendations/generate', {
        'destinationArea': requestedArea,
        if (geographicMode == 'nearby') 'geographicMode': 'nearby',
        if (selectedLocation?['canonicalName'] == requestedArea) 'destinationScopeKey': selectedLocation!['scopeKey'],
        if (selectedLocation?['canonicalName'] == requestedArea && selectedLocation?['locationId'] != null)
          'destinationLocationId': selectedLocation!['locationId'],
        'discoveryMode':recommendationDiscoveryMode,
        if ((reuseCandidates || expand) && generatedDestination == requestedArea && recommendationGenerationId.isNotEmpty)
          'previousGenerationId': recommendationGenerationId,
        if (expand) 'expandCandidates': true,
        if (expand) 'displayedDestinationIds': items.whereType<Map>().map((row) => _destinationId(Map<String, dynamic>.from(row))).toList(),
      });
      if (!mounted || version != requestVersion || data is! Map) return;
      validateDiscoveryResponse(data);
      setState(() {
        final received = data['recommendations'] as List? ?? [];
        items = expand ? appendRecommendationResults(items, received) : received;
        discoveryNotice = data['discoveryMessage']?.toString();
        searchMessage = data['snapshot']?['searchMessage']?.toString();
        coverageNotice = data['snapshot']?['coverageNotice']?.toString();
        nearbyAvailable = data['snapshot']?['nearbyAvailable'] == true;
        generatedScope = Map<String, dynamic>.from(data['snapshot']?['canonicalDestinationScope'] as Map? ?? {});
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
      if (mounted) setState(() { generationInFlight = false; busy = false; });
    }
  }

  void changeDestination(String value) {
    setState(() {
      ++locationLookupVersion;
      lookupMatches = []; locationLookupBusy = false; locationNotice = null;
      if (selectedLocation?['canonicalName'] != value.trim()) selectedLocation = null;
      if (value.trim() != generatedDestination) {
        coverageNotice = null;
        geographicMode = 'strict';
        nearbyAvailable = false;
        ++requestVersion;
        items = []; pagination = {}; recommendationGenerationId = ''; generatedScope = {};
        busy = generationInFlight; loadingMore = false; discoveryNotice = null; searchMessage = null;
      }
    });
  }

  void chooseLocation(Map<String, dynamic> row) {
    FocusScope.of(context).unfocus();
    selectedLocation = row;
    destination.text = row['canonicalName'] as String;
    changeDestination(destination.text);
    setState(() => ++destinationSelection);
  }

  Future<void> changeGeographicMode(String mode) async {
    if (busy || loadingMore || generationInFlight || !nearbyAvailable) return;
    setState(() {
      geographicMode = mode;
      coverageNotice = null;
      items = []; pagination = {}; recommendationGenerationId = '';
      generatedScope = {}; generatedDestination = ''; searchMessage = null;
    });
    await generate();
  }

  Future<void> findLocation() async {
    final query = destination.text.trim();
    if (locationLookupBusy || query.length < 2) return;
    final version = ++locationLookupVersion;
    setState(() { locationLookupBusy = true; locationNotice = null; lookupMatches = []; });
    try {
      final data = await api.get('/api/fr4/locations/search', {'q': query, 'remote': 'true'});
      if (!mounted || version != locationLookupVersion || destination.text.trim() != query) return;
      setState(() {
        lookupMatches = (data['locations'] as List? ?? []).whereType<Map>().map((r) => Map<String, dynamic>.from(r)).toList();
        locationNotice = lookupMatches.isEmpty ? 'No verified Malaysian location found. Try its town and state.' : 'Choose the matching Malaysian location.';
      });
    } catch (_) {
      if (mounted && version == locationLookupVersion) setState(() => locationNotice = 'Additional location lookup is unavailable. Existing suggestions remain available.');
    } finally {
      if (mounted && version == locationLookupVersion) setState(() => locationLookupBusy = false);
    }
  }

  Future<void> loadPage({bool reset = false}) async {
    if (loadingMore || recommendationGenerationId.isEmpty) return;
    final version = ++requestVersion;
    setState(() { loadingMore = true; errorMessage = null; });
    try {
      final data = await api.get('/api/fr4/recommendations', {
        'generationId': recommendationGenerationId, 'discoveryMode':recommendationDiscoveryMode,
        'offset': reset ? '0' : '${pagination['nextOffset'] ?? 0}',
      });
      if (!mounted || version != requestVersion) return;
      if (data['stale'] == true) {
        setState(() => loadingMore = false);
        await generate(reuseCandidates:true);
        return;
      }
      validateDiscoveryResponse(data);
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
      if (!mounted || !await addTripVisit(context, api, selected['id'].toString(), {
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
      })) return;
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
    final qualified = items.whereType<Map>().where((item) => item['discoveryEligible'] == true).toList();
    return Scaffold(
      appBar: AppBar(title: const Text('For you'), actions: [
        if (demonstrationAvailable) IconButton(icon: const Icon(Icons.science_outlined),
          tooltip: 'Demonstration review data', onPressed: () => Navigator.push(context,
            MaterialPageRoute(builder: (_) => DemonstrationRecommendationsScreen(api: api)))),
      ]),
      body: RefreshIndicator(
        onRefresh: () async {
          LocalReviewRatings.invalidate();
          await generate();
        },
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
            if (recommendationsNeedEvidenceUpdate(items)) ...[
              const SizedBox(height: AppSpacing.md),
              RecommendationEvidenceNotice(onRegenerate: busy ? null : () => generate()),
            ],
            const SizedBox(height: AppSpacing.md),
            LayoutBuilder(key: const ValueKey('recommendation-location-field'), builder: (context, constraints) => RawAutocomplete<Map<String, dynamic>>(
              key: ValueKey('destination-$generatedDestination-$destinationSelection'),
              initialValue: TextEditingValue(text: destination.text),
              displayStringForOption: (row) => row['canonicalName'] as String,
              optionsBuilder: (value) => matchingMalaysianLocations(locations, value.text),
              onSelected: chooseLocation,
              fieldViewBuilder: (_, controller, focus, submit) {
                return TextField(
                controller: controller, focusNode: focus,
                decoration: const InputDecoration(labelText: 'Destination area', hintText: 'e.g. Penang, Malaysia', prefixIcon: Icon(Icons.location_on_outlined)),
                onChanged: (value) { destination.text = value; changeDestination(value); }, textInputAction: TextInputAction.search,
                onSubmitted: (_) { focus.unfocus(); if (!busy) generate(); },
              ); },
              optionsViewBuilder: (_, choose, options) => Align(alignment: Alignment.topLeft,
                child: Material(elevation: 4, borderRadius: AppRadii.control,
                  child: SizedBox(width: constraints.maxWidth, height: 220,
                    child: ListView(padding: EdgeInsets.zero, children: options.map((row) => ListTile(
                      title: Text(row['canonicalName'] as String),
                      subtitle: Text(row['kind'] == 'state' ? 'State / federal territory' : '${row['kind'] ?? 'Locality'} · ${row['district'] ?? row['state'] ?? 'Malaysia'}'),
                      onTap: () => choose(row),
                    )).toList())),
                )),
            )),
            if (locationsLoading) const Text('Loading Malaysian locations…'),
            Align(alignment: Alignment.centerLeft, child: TextButton.icon(
              onPressed: locationLookupBusy ? null : findLocation,
              icon: locationLookupBusy ? const SizedBox(width: 16, height: 16, child: CircularProgressIndicator(strokeWidth: 2)) : const Icon(Icons.location_searching),
              label: const Text('Find more Malaysian locations'),
            )),
            if (locationNotice != null) Text(locationNotice!),
            Wrap(children: [
              TextButton(onPressed: () => launchUrl(Uri.parse('https://www.geonames.org/'), mode: LaunchMode.externalApplication),
                child: const Text('GeoNames · CC BY 4.0')),
              if (selectedLocation?['dataSource'] == 'open_meteo_geonames' || lookupMatches.any((row) => row['dataSource'] == 'open_meteo_geonames'))
                TextButton(onPressed: () => launchUrl(Uri.parse('https://open-meteo.com/en/docs/geocoding-api'), mode: LaunchMode.externalApplication),
                  child: const Text('Location lookup by Open-Meteo · CC BY-NC 4.0')),
            ]),
            if (lookupMatches.isNotEmpty) SizedBox(height: 200, child: ListView(
              children: lookupMatches.map((row) => ListTile(
                title: Text('${row['canonicalName']}'),
                subtitle: Text('${row['kind'] ?? 'Locality'} · ${row['district'] ?? row['state'] ?? 'Malaysia'}'),
                onTap: () => chooseLocation(row),
              )).toList(),
            )),
            const SizedBox(height: AppSpacing.sm),
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
            if (errorMessage != null && qualified.isNotEmpty) ...[
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
              Column(children: [TravelEmptyState(
                icon: Icons.auto_awesome_outlined,
                title: 'No relevant suggestions available yet',
                message: searchMessage ?? 'The current places do not have supported matches to your interests in $generatedDestination. Discover more places or update your preferences.',
                actionLabel: 'Discover suggestions',
                onAction: generate,
              ),
                if (generatedScope['city'] != null && locations.any((row) => row['kind'] == 'state' && row['state'] == generatedScope['state']))
                  TextButton(onPressed: () => chooseLocation(locations.firstWhere((row) => row['kind'] == 'state' && row['state'] == generatedScope['state'])),
                    child: Text('Use wider area: ${generatedScope['state']} (then search again)')),
              ])
            else
              ...qualified.map((raw) {
                final item = Map<String, dynamic>.from(raw);
                return Padding(
                  padding: const EdgeInsets.only(bottom: AppSpacing.md),
                  child: RecommendationCard(
                    onRefreshEvidence: busy ? null : () => generate(),
                    recommendation: item,
                    discovery:true,
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
            if (coverageNotice != null) Text(coverageNotice!),
            if ((preferences['interests'] as List? ?? []).length > 1 && items.any((row) => row is Map && row['selectionPolicy'] == 'strong_interest_coverage_v1'))
              const Text('Order balances strongly evidenced interests. Hybrid scores remain unchanged.'),
            if (nearbyAvailable) ...[
              const SizedBox(height: AppSpacing.sm),
              Text(geographicMode == 'nearby'
                ? 'Nearby places within 10 km of ${generatedScope['canonicalName']}. Distances are straight-line, not travel times.'
                : 'Exact locality matches. Nearby places require a separate search.'),
              TextButton(onPressed: busy ? null : () => changeGeographicMode(geographicMode == 'nearby' ? 'strict' : 'nearby'),
                child: Text(geographicMode == 'nearby' ? 'Search exact locality' : 'Explore nearby places (10 km)')),
            ],
            if (pagination['hasMore'] == true)
              PrimaryButton(label:'Load more matching places', loading:loadingMore, onPressed:() => loadPage()),
            if (discoveryNotice != null)
              Padding(padding: const EdgeInsets.symmetric(vertical: 12), child: Text(discoveryNotice!)),
            if (pagination['hasMore'] != true && items.isNotEmpty)
              PrimaryButton(label:'Discover more places', loading:busy, onPressed:() => generate(expand:true)),
          ],
        ),
      ),
    );
  }
}
