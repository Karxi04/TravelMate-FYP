import 'package:flutter/material.dart';

import '../../core/utils/destination_utils.dart';
import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/destination_card.dart';
import '../../widgets/local_place_rating.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr04_hybrid_recommendation/recommendation_screen.dart';
import 'destination_details_screen.dart';
import 'destination_trip_actions.dart';
import 'favourites_screen.dart';
import 'favourites_controller.dart';

class ExploreTab extends StatefulWidget {
  final String initialQuery;
  final String initialLocation;
  final ApiService? api;

  const ExploreTab({
    super.key,
    this.initialQuery = '',
    this.initialLocation = 'Malaysia',
    this.api,
  });

  @override
  State<ExploreTab> createState() => _ExploreTabState();
}

class _ExploreTabState extends State<ExploreTab> {
  late final TextEditingController query;
  late final TextEditingController location;
  late final ApiService api;

  List<Map<String, dynamic>> results = [];
  final Set<String> addingIds = {};
  late final FavouritesController favourites;

  void _favouritesChanged() { if (mounted) setState(() {}); }
  bool loading = false;
  bool hasSearched = false;
  String sort = 'relevance';
  String locationUsed = '';
  String resultSource = '';
  String? queryError;
  String? searchError;
  int searchVersion = 0;
  int visibleLimit = 20;
  int? nextOffset;
  String? _resultCriteria;
  String? _pendingCriteria;
  String get _criteria => '${query.text.trim()}|${location.text.trim()}|$sort';

  final suggestions = const [
    'Malaysia attractions',
    'Local food',
    'Heritage places',
    'Nature escapes',
  ];

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    favourites = FavouritesController(api)..addListener(_favouritesChanged);
    query = TextEditingController(text: widget.initialQuery);
    location = TextEditingController(text: widget.initialLocation);
    if (widget.initialQuery.trim().isNotEmpty) Future.microtask(search);
  }

  @override
  void dispose() {
    favourites.removeListener(_favouritesChanged);
    favourites.dispose();
    query.dispose();
    location.dispose();
    super.dispose();
  }

  bool get _showSourceDisclosure => const {
        'cache',
        'cached',
        'fallback',
        'local',
        'demo',
      }.contains(resultSource.toLowerCase());

  String get _locationTitle {
    final value = location.text.trim();
    if (value.isEmpty || value.toLowerCase() == 'malaysia') return 'Malaysia';
    return value.split(',').first.trim();
  }

  Future<void> search({bool loadMore = false}) async {
    final text = query.text.trim();
    if (text.isEmpty) {
      setState(
          () => queryError = 'Enter a place, food, or activity to search.');
      return;
    }
    if (loadMore && (_resultCriteria != _criteria || nextOffset == null)) return;
    final requestedCriteria = _criteria;
    if (loading && _pendingCriteria == requestedCriteria) return;
    _pendingCriteria = requestedCriteria;
    final version = ++searchVersion;
    final previous = loadMore ? List<Map<String, dynamic>>.from(results) : <Map<String, dynamic>>[];
    FocusManager.instance.primaryFocus?.unfocus();
    setState(() {
      loading = true;
      hasSearched = true;
      queryError = null;
      searchError = null;
      if (!loadMore) {
        results = [];
        nextOffset = null;
        _resultCriteria = null;
      }
    });

    final requestedLocation =
        location.text.trim().isEmpty ? 'Malaysia' : location.text.trim();
    final params = <String, String>{
      'q': text,
      'location': requestedLocation,
      if (loadMore) 'offset': '$nextOffset',
    };
    if (sort != 'relevance') params['sort'] = sort;

    try {
      final data = await api.get('/api/fr3/destinations/search', params);
      if (!mounted || version != searchVersion || requestedCriteria != _criteria) return;
      setState(() {
        final incoming = (data['results'] as List? ?? const [])
            .whereType<Map>()
            .map((item) => Map<String, dynamic>.from(item))
            .toList();
        final unique = <String, Map<String, dynamic>>{};
        for (final item in [...previous, ...incoming]) { unique.putIfAbsent(DestinationUtils.resolveId(item), () => item); }
        results = unique.values.toList();
        if (loadMore) visibleLimit += 20;
        nextOffset = data['nextOffset'] as int?;
        _resultCriteria = requestedCriteria;
        locationUsed =
            (data['locationUsed'] ?? requestedLocation).toString().trim();
        resultSource = (data['source'] ?? '').toString();
      });
    } catch (error) {
      if (!mounted || version != searchVersion || requestedCriteria != _criteria) return;
      setState(() {
        searchError = userFacingApiError(error);
      });
    } finally {
      if (mounted && version == searchVersion) setState(() => loading = false);
    }
  }

  void _onCriteriaEdited(String _) {
    if (!hasSearched && queryError == null) return;
    searchVersion++;
    setState(() {
      loading = false;
      hasSearched = false;
      results = [];
      nextOffset = null;
      queryError = null;
      searchError = null;
    });
  }

  Future<void> _addToTrip(Map<String, dynamic> item) async {
    final id = DestinationUtils.resolveId(item);
    if (addingIds.contains(id)) return;
    setState(() => addingIds.add(id));
    await addDestinationToTrip(
      context: context,
      api: api,
      destination: item,
    );
    if (mounted) setState(() => addingIds.remove(id));
  }

  Future<void> _saveDestination(Map<String, dynamic> item) async {
    try {
      await favourites.toggle(item);
    } catch (error) {
      if (mounted) showError(context, error);
    }
  }

  bool _isArea(Map<String, dynamic> item) => item['resultKind'] == 'area';

  Future<void> _viewResult(Map<String, dynamic> item) async {
    if (_isArea(item)) {
      final area = (item['title'] ?? item['name'] ?? '').toString().trim();
      if (area.isEmpty) return;
      location.text = area;
      query.text = 'places to visit';
      query.selection = TextSelection.collapsed(offset: query.text.length);
      await search();
      return;
    }
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => DestinationDetailsScreen(
          initialDestination: Map<String, dynamic>.from(item),
          api: api,
        ),
      ),
    );
  }

  void _useSuggestion(String value) {
    query.text = value;
    query.selection = TextSelection.collapsed(offset: value.length);
    search();
  }

  Widget _searchControls() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SearchField(
            key: const ValueKey('explore-search-field'),
            controller: query,
            hint: 'Search places, food, attractions…',
            onChanged: _onCriteriaEdited,
            onSubmitted: (_) => search(),
            onClear: () {
              query.clear();
              _onCriteriaEdited('');
            },
          ),
          if (queryError != null) ...[
            const SizedBox(height: AppSpacing.xxs),
            Text(
              queryError!,
              style: Theme.of(context)
                  .textTheme
                  .bodySmall
                  ?.copyWith(color: AppColors.error),
            ),
          ],
          const SizedBox(height: AppSpacing.sm),
          AppTextField(
            key: const ValueKey('explore-location-field'),
            controller: location,
            label: 'Search area',
            hint: 'Penang, Kuala Lumpur…',
            prefixIcon: Icons.location_on_outlined,
            textInputAction: TextInputAction.search,
            onChanged: _onCriteriaEdited,
            onSubmitted: (_) => search(),
          ),
          const SizedBox(height: AppSpacing.sm),
          SizedBox(
            width: double.infinity,
            child: PrimaryButton(
              key: const ValueKey('explore-search-button'),
              label: loading ? 'Searching…' : 'Search places',
              icon: Icons.travel_explore_rounded,
              onPressed: loading ? null : search,
            ),
          ),
        ],
      );

  Widget _filters() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Expanded(
                child: Text(
                  hasSearched ? 'Results' : 'Discover',
                  style: Theme.of(context).textTheme.titleMedium,
                ),
              ),
              PopupMenuButton<String>(
                key: const ValueKey('explore-sort-menu'),
                initialValue: sort,
                tooltip: 'Sort destinations',
                onSelected: (value) {
                  setState(() => sort = value);
                  if (hasSearched) search();
                },
                itemBuilder: (_) => const [
                  PopupMenuItem(value: 'relevance', child: Text('Relevance')),
                  PopupMenuItem(value: 'rating', child: Text('Highest rating')),
                  PopupMenuItem(value: 'name', child: Text('Name')),
                ],
                child: StatusChip(
                  text: switch (sort) {
                    'rating' => 'Highest rating',
                    'name' => 'Name',
                    _ => 'Relevance',
                  },
                  icon: Icons.sort_rounded,
                  tone: AppStatusTone.neutral,
                ),
              ),
            ],
          ),
        ],
      );

  Widget _resultState() {
    if (loading && results.isEmpty) {
      return const InkCard(
        child: AppLoadingState(message: 'Finding places…'),
      );
    }
    if (searchError != null && results.isEmpty) {
      return AppErrorState(
        title: 'Places couldn’t be loaded',
        message: searchError!,
        onRetry: search,
      );
    }
    if (!hasSearched) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Wrap(
            spacing: AppSpacing.xs,
            runSpacing: AppSpacing.xs,
            children: suggestions
                .map(
                  (suggestion) => ActionChip(
                    label: Text(suggestion),
                    onPressed: () => _useSuggestion(suggestion),
                  ),
                )
                .toList(),
          ),
          const SizedBox(height: AppSpacing.md),
          const TravelEmptyState(
            icon: Icons.map_outlined,
            title: 'Find somewhere memorable',
            message:
                'Search a place, dish, attraction, or activity in your chosen area.',
          ),
        ],
      );
    }
    if (results.isEmpty) {
      return TravelEmptyState(
        icon: Icons.search_off_rounded,
        title: 'No places found',
        message: 'Try a broader search term or another area.',
      );
    }

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (loading) ...[
          const LinearProgressIndicator(),
          const SizedBox(height: AppSpacing.sm),
        ],
        if (searchError != null) ...[
          InkCard(
            color: AppColors.errorSoft,
            child: Row(
              children: [
                const Icon(Icons.error_outline_rounded, color: AppColors.error),
                const SizedBox(width: AppSpacing.xs),
                Expanded(child: Text(searchError!)),
                TextButton(onPressed: search, child: const Text('Retry')),
              ],
            ),
          ),
          const SizedBox(height: AppSpacing.sm),
        ],
        Row(
          children: [
            Expanded(
              child: Text(
                '${results.length} place${results.length == 1 ? '' : 's'}${locationUsed.isEmpty ? '' : ' in $locationUsed'}',
                style: Theme.of(context)
                    .textTheme
                    .bodyMedium
                    ?.copyWith(color: AppColors.textSecondary),
              ),
            ),
            if (_showSourceDisclosure)
              SourceFallbackBadge(source: resultSource),
          ],
        ),
        const SizedBox(height: AppSpacing.sm),
        DropdownButtonFormField<int>(key: ValueKey(visibleLimit), initialValue: visibleLimit,
          decoration: const InputDecoration(labelText: 'Places to show'),
          items: [const DropdownMenuItem(value: 10, child: Text('10 places')),
            const DropdownMenuItem(value: 20, child: Text('20 places')), const DropdownMenuItem(value: 40, child: Text('40 places')),
            if (![10,20,40].contains(visibleLimit)) DropdownMenuItem(value: visibleLimit, child: Text('$visibleLimit places'))],
          onChanged: (value) { if (value != null) setState(() => visibleLimit = value); }),
        const SizedBox(height: AppSpacing.md),
        ...results.take(visibleLimit).map(
          (item) => Padding(
            padding: const EdgeInsets.only(bottom: AppSpacing.sm),
            child: DestinationCard(
              destination: item,
              source: resultSource,
              onView: () => _viewResult(item),
              saved: favourites.contains(DestinationUtils.resolveId(item)),
              saveEnabled: favourites.loaded && favourites.error == null &&
                  !favourites.busyIds.contains(DestinationUtils.resolveId(item)),
              onSave: _isArea(item) ? null : () => _saveDestination(item),
              onAddToTrip: _isArea(item) ||
                      addingIds.contains(DestinationUtils.resolveId(item))
                  ? null
                  : () => _addToTrip(item),
            ),
          ),
        ),
        const SizedBox(height: AppSpacing.md),
        if (results.length > visibleLimit || nextOffset != null)
          OutlinedButton(
            onPressed: loading ? null : () {
              if (results.length > visibleLimit) {
                setState(() => visibleLimit += 20);
              } else {
                search(loadMore: true);
              }
            },
            child: Text(loading ? 'Loading more places…' : 'Load more places'),
          )
        else
          const Center(child: Text('All matching places shown')),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return TravelMatePageScaffold(
      appBar: AppBar(
        title: const Text('Explore'),
        actions: [
          IconButton(
            tooltip: 'Personalised recommendations',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => const RecommendationScreen()),
            ),
            icon: const Icon(Icons.auto_awesome_outlined),
          ),
          IconButton(
            tooltip: 'Saved destinations',
            onPressed: () => Navigator.push(
              context,
              MaterialPageRoute(builder: (_) => FavouritesScreen(api: api)),
            ),
            icon: const Icon(Icons.favorite_border_rounded),
          ),
        ],
      ),
      padding: EdgeInsets.zero,
      body: RefreshIndicator(
        onRefresh: () async {
          LocalReviewRatings.invalidate();
          await favourites.load();
          if (hasSearched) await search();
        },
        child: ListView(
          key: const ValueKey('explore-scroll'),
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            AppSpacing.xs,
            AppSpacing.md,
            AppSpacing.xxl,
          ),
          children: [
            AppSectionHeader(
              title: 'Explore $_locationTitle',
              subtitle: 'Search, discover, and add places to your trip.',
            ),
            const SizedBox(height: AppSpacing.md),
            _searchControls(),
            const SizedBox(height: AppSpacing.lg),
            _filters(),
            const SizedBox(height: AppSpacing.md),
            if (favourites.error != null) AppErrorState(message: favourites.error!, onRetry: favourites.load),
            _resultState(),
          ],
        ),
      ),
    );
  }
}
