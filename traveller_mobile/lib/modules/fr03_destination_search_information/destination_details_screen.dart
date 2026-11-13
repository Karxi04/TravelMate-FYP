import 'package:flutter/material.dart';

import '../../core/utils/destination_utils.dart';
import '../../core/utils/opening_hours_utils.dart';
import '../../widgets/local_place_rating.dart';
import '../../services/api_service.dart';
import '../../services/review_contract.dart';
import '../../theme/app_theme.dart';
import '../../widgets/destination_card.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr10_feedback_rating/feedback_screen.dart';
import 'destination_trip_actions.dart';
import 'favourites_controller.dart';

class DestinationDetailsScreen extends StatefulWidget {
  final Map<String, dynamic> initialDestination;
  final ApiService? api;

  const DestinationDetailsScreen({
    super.key,
    required this.initialDestination,
    this.api,
  });

  @override
  State<DestinationDetailsScreen> createState() =>
      _DestinationDetailsScreenState();
}

class _DestinationDetailsScreenState extends State<DestinationDetailsScreen> {
  late final ApiService api;
  late Map<String, dynamic> detail;

  Map<String, dynamic>? reviewInfo;
  List<Map<String, dynamic>> nearbyPlaces = [];
  bool loading = true;
  bool saving = false;
  bool adding = false;
  late final FavouritesController favourites;
  bool get saved => favourites.contains(destinationId);
  void _favouritesChanged() { if (mounted) setState(() {}); }
  bool showAllReviews = false;
  bool communityReviews = false;
  bool hasPrivateReviewPreview = false;
  bool hasLocalSampleReviews = false;
  bool sampleReviews = false;
  int _loadRevision = 0;
  bool detailsFailed = false;
  bool reviewsFailed = false;
  bool nearbyFailed = false;
  String source = '';
  bool providerFallback = false;

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    detail = Map<String, dynamic>.from(widget.initialDestination);
    favourites = FavouritesController(api)..addListener(_favouritesChanged);
    Future.microtask(loadDetails);
  }

  String get destinationId {
    final id = DestinationUtils.resolveId(detail);
    return id.isEmpty ? title : id;
  }
  String get title => DestinationUtils.resolveName(detail);
  String get reviewDestinationId {
    final openedId = DestinationUtils.resolveId(widget.initialDestination);
    return ReviewContract.destinationId(openedId.isEmpty ? destinationId : openedId);
  }
  String get address =>
      (detail['address'] ?? detail['location'] ?? '').toString().trim();
  String get category =>
      (detail['category'] ?? detail['type'] ?? '').toString().trim();

  bool get _showSourceDisclosure => const {
        'cache',
        'cached',
        'fallback',
        'local',
        'demo',
      }.contains(source.toLowerCase());

  bool get _hasEssentialDetails =>
      (title.isNotEmpty &&
          title != 'Place' &&
          title != 'Destination') ||
      address.isNotEmpty;

  String get _materialWarning => _text(
        detail['bookingWarning'] ??
            detail['pricingWarning'] ??
            detail['materialWarning'] ??
            detail['bookingNotice'] ??
            detail['availabilityWarning'],
      );

  Future<void> loadDetails() async {
    if (!mounted) return;
    final revision = ++_loadRevision;
    final reviewOwner = LocalReviewRatings.accountUid;
    bool current() => mounted && revision == _loadRevision &&
        reviewOwner == LocalReviewRatings.accountUid;
    final id = destinationId;
    if (id.isEmpty) {
      setState(() {
        loading = false;
        detailsFailed = true;
      });
      return;
    }

    setState(() {
      loading = true;
      detailsFailed = false;
      reviewsFailed = false;
      reviewInfo = null;
      nearbyFailed = false;
      providerFallback = false;
    });
    final encoded = Uri.encodeComponent(id);

    try {
      final data = await api.get('/api/fr3/destinations/$encoded');
      if (!current()) return;
      if (data['destination'] is Map) {
        final fetched = Map<String, dynamic>.from(data['destination'] as Map);
        final hours = OpeningHoursUtils.parse(fetched);
        detail = {
          ...detail,
          ...fetched,
          if (hours.hasWeeklySchedule) 'weeklyHours': Map.fromEntries(
            hours.weeklyHours.where((entry) => entry.value != 'Not available')),
        };
      }
      source = (data['source'] ?? '').toString();
      providerFallback = data['providerWarning'] != null;
    } catch (_) {
      if (!current()) return;
      detailsFailed = true;
    }

    try {
      final reviewId = Uri.encodeComponent(reviewDestinationId);
      final path = '/api/fr3/destinations/$reviewId/ratings-reviews';
      final data = sampleReviews
          ? await api.get(path, {'view': 'samples'})
          : communityReviews
              ? await api.get(path, {'view': 'community'})
              : await api.get(path);
      if (!current()) return;
      hasLocalSampleReviews = data['sampleReviewsAvailable'] == true;
      reviewInfo = data['result'] is Map
          ? Map<String, dynamic>.from(data['result'] as Map)
          : null;
      if (reviewInfo == null) {
        reviewsFailed = true;
      } else {
        final preview = reviewInfo!['fypPreview'] == true;
        if (!hasLocalSampleReviews && preview) hasPrivateReviewPreview = true;
        if (!preview && !communityReviews && !sampleReviews) {
          LocalReviewRatings.remember(reviewDestinationId, reviewInfo!);
        }
      }
    } catch (_) {
      if (!current()) return;
      reviewsFailed = true;
    }

    try {
      final data = await api.get(
        '/api/fr3/destinations/$encoded/nearby',
        {'radiusKm': '12'},
      );
      if (!current()) return;
      nearbyPlaces = (data['items'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
    } catch (_) {
      if (!current()) return;
      nearbyFailed = true;
    }

    if (current()) setState(() => loading = false);
  }

  @override
  void dispose() {
    favourites.removeListener(_favouritesChanged);
    favourites.dispose();
    super.dispose();
  }

  Future<void> saveFavourite() async {
    if (saving) return;
    setState(() => saving = true);
    try {
      await favourites.toggle({...detail, 'destinationId': destinationId});
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Future<void> addToItinerary([Map<String, dynamic>? destination]) async {
    if (adding) return;
    setState(() => adding = true);
    await addDestinationToTrip(
      context: context,
      api: api,
      destination: destination ?? detail,
    );
    if (mounted) setState(() => adding = false);
  }

  String _text(dynamic value) {
    if (value == null || value is Map || value is List) return '';
    final result = value.toString().trim();
    if (result.isEmpty ||
        {'null', 'n/a', 'na', '-', 'unknown'}.contains(result.toLowerCase())) {
      return '';
    }
    return result;
  }

  OpeningHoursSchedule _openingSchedule() => OpeningHoursUtils.parse(detail);

  List<String> _personalReasons() {
    final reasons = <String>[];
    final rawList = detail['matchReasons'];
    if (rawList is List) {
      reasons.addAll(rawList.map((value) => value.toString().trim()));
    } else {
      final raw =
          (detail['recommendationReason'] ?? detail['reason'] ?? '').toString();
      reasons.addAll(raw.split('•').map((value) => value.trim()));
    }
    final internal = RegExp(
      r'(content|collaborative|popularity|final)\s*score|^\d+(\.\d+)?%\s*match$',
      caseSensitive: false,
    );
    return reasons
        .where((reason) => reason.isNotEmpty && !internal.hasMatch(reason))
        .take(2)
        .toList();
  }

  List<Map<String, dynamic>> _reviews() {
    final raw = reviewInfo?['user_reviews'];
    if (raw is List) {
      return raw
          .whereType<Map>()
          .map((review) => Map<String, dynamic>.from(review))
          .toList();
    }
    if (raw is Map) {
      for (final key in ['most_relevant', 'reviews', 'items']) {
        final value = raw[key];
        if (value is List) {
          return value
              .whereType<Map>()
              .map((review) => Map<String, dynamic>.from(review))
              .toList();
        }
      }
    }
    return const [];
  }

  String _reviewAuthor(Map<String, dynamic> review) {
    final user = review['user'];
    if (user is Map) {
      return (user['name'] ?? user['username'] ?? 'Traveller').toString();
    }
    return (review['username'] ?? review['author'] ?? 'Traveller').toString();
  }

  Widget _hero() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TravelPlaceImage(
            place: detail,
            width: double.infinity,
            height: null,
            aspectRatio: AppSizes.destinationImageAspectRatio,
            borderRadius: AppRadii.card,
          ),
          const SizedBox(height: AppSpacing.md),
          Text(title, style: Theme.of(context).textTheme.headlineMedium),
          if (address.isNotEmpty) ...[
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
                    address,
                    style: Theme.of(context)
                        .textTheme
                        .bodyMedium
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
              if (category.isNotEmpty)
                StatusChip(text: category, tone: AppStatusTone.neutral),
              if (_showSourceDisclosure) SourceFallbackBadge(source: source),
            ],
          ),
        ],
      );

  Widget _personalContext() {
    final reasons = _personalReasons();
    if (reasons.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppSectionHeader(title: 'Why this fits you'),
        const SizedBox(height: AppSpacing.sm),
        InkCard(
          color: AppColors.primarySoft,
          child: Column(
            children: reasons
                .map(
                  (reason) => Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.xs),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.check_circle_outline_rounded,
                          size: AppSizes.icon,
                          color: AppColors.primary,
                        ),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(child: Text(reason)),
                      ],
                    ),
                  ),
                )
                .toList(),
          ),
        ),
      ],
    );
  }

  Widget _informationRow(
    IconData icon,
    String label,
    String value, {
    String? subtitle,
  }) {
    if (value.isEmpty) return const SizedBox.shrink();
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 40,
            height: 40,
            decoration: BoxDecoration(
              color: AppColors.primarySoft,
              borderRadius: AppRadii.control,
            ),
            child: Icon(icon, size: AppSizes.icon, color: AppColors.primary),
          ),
          const SizedBox(width: AppSpacing.sm),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: Theme.of(context)
                      .textTheme
                      .bodySmall
                      ?.copyWith(color: AppColors.textSecondary),
                ),
                const SizedBox(height: AppSpacing.xxs),
                Text(value, style: Theme.of(context).textTheme.bodyMedium),
                if (subtitle != null && subtitle.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: Theme.of(context)
                        .textTheme
                        .bodySmall
                        ?.copyWith(color: AppColors.textSecondary),
                  ),
                ],
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _visitInformation() {
    final schedule = _openingSchedule();
    final duration = int.tryParse(
          '${detail['recommendedDurationMinutes'] ?? ''}',
        ) ??
        0;
    final estimatedCost = num.tryParse('${detail['estimatedCost'] ?? ''}');
    final admission = _text(detail['admission']);
    final bestTime = _text(detail['bestTime']);
    final price = _text(detail['price']);
    final phone = _text(detail['phone']);
    final links = detail['links'];
    final website = _text(
      detail['website'] ?? (links is Map ? links['website'] : null),
    );
    final materialWarning = _materialWarning;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const AppSectionHeader(title: 'Visit information'),
        const SizedBox(height: AppSpacing.sm),
        InkCard(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (schedule.isUnavailable)
                _informationRow(
                  Icons.schedule_outlined,
                  'Opening hours',
                  'Opening hours not available',
                  subtitle: 'Check with the attraction before visiting.',
                )
              else if (!schedule.hasWeeklySchedule &&
                  schedule.genericHours != null)
                _informationRow(
                  Icons.schedule_outlined,
                  'General opening hours',
                  schedule.genericHours!,
                  subtitle: 'Hours for individual days or holidays may vary.',
                )
              else ...[
                _informationRow(
                  Icons.schedule_outlined,
                  'Opening hours',
                  schedule.realTimeStatus != null
                      ? 'Weekly schedule (${schedule.realTimeStatus})'
                      : 'Weekly schedule',
                ),
                Padding(
                  padding: const EdgeInsets.only(
                    left: 52,
                    bottom: AppSpacing.sm,
                  ),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      ...schedule.weeklyHours.map(
                        (entry) {
                          final isToday =
                              entry.key == schedule.currentMalaysiaDay;
                          final isClosed =
                              entry.value.toLowerCase().contains('closed');
                          return Container(
                            margin: const EdgeInsets.only(bottom: 6),
                            padding: isToday
                                ? const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 4,
                                  )
                                : const EdgeInsets.symmetric(
                                    horizontal: 4,
                                    vertical: 2,
                                  ),
                            decoration: isToday
                                ? BoxDecoration(
                                    color: AppColors.primarySoft,
                                    borderRadius: AppRadii.control,
                                  )
                                : null,
                            child: Row(
                              crossAxisAlignment: CrossAxisAlignment.start,
                              children: [
                                ConstrainedBox(
                                  constraints:
                                      const BoxConstraints(minWidth: 80),
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        entry.key,
                                        style: Theme.of(context)
                                            .textTheme
                                            .bodySmall
                                            ?.copyWith(
                                              fontWeight: isToday
                                                  ? FontWeight.w700
                                                  : FontWeight.w500,
                                              color: isToday
                                                  ? AppColors.primary
                                                  : AppColors.textPrimary,
                                            ),
                                      ),
                                      if (isToday) ...[
                                        const SizedBox(height: 2),
                                        Container(
                                          padding: const EdgeInsets.symmetric(
                                            horizontal: 4,
                                            vertical: 1,
                                          ),
                                          decoration: BoxDecoration(
                                            color: AppColors.primary,
                                            borderRadius:
                                                BorderRadius.circular(3),
                                          ),
                                          child: const Text(
                                            'Today',
                                            style: TextStyle(
                                              color: Colors.white,
                                              fontSize: 9,
                                              fontWeight: FontWeight.bold,
                                            ),
                                          ),
                                        ),
                                      ],
                                    ],
                                  ),
                                ),
                                const SizedBox(width: AppSpacing.sm),
                                Expanded(
                                  child: Text(
                                    entry.value,
                                    style: Theme.of(context)
                                        .textTheme
                                        .bodySmall
                                        ?.copyWith(
                                          color: isClosed
                                              ? AppColors.textSecondary
                                              : (isToday
                                                  ? AppColors.primary
                                                  : AppColors.textPrimary),
                                          fontWeight: isToday
                                              ? FontWeight.w600
                                              : FontWeight.normal,
                                          fontStyle: isClosed
                                              ? FontStyle.italic
                                              : FontStyle.normal,
                                        ),
                                  ),
                                ),
                              ],
                            ),
                          );
                        },
                      ),
                      const SizedBox(height: 2),
                      const Text(
                        'Hours may change on public holidays.',
                        style: TextStyle(
                          color: AppColors.textSecondary,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
              if (address.isNotEmpty)
                _informationRow(Icons.place_outlined, 'Address', address),
              if (duration > 0)
                _informationRow(
                  Icons.timelapse_rounded,
                  'Suggested visit duration',
                  'About $duration minutes',
                ),
              if (estimatedCost != null && estimatedCost > 0)
                _informationRow(
                  Icons.account_balance_wallet_outlined,
                  'Estimated activity cost',
                  'About RM ${estimatedCost % 1 == 0 ? estimatedCost.toInt() : estimatedCost.toStringAsFixed(2)}',
                ),
              _informationRow(
                Icons.confirmation_number_outlined,
                'Admission',
                admission,
              ),
              if (materialWarning.isNotEmpty) ...[
                Padding(
                  padding: const EdgeInsets.only(
                    left: 52,
                    bottom: AppSpacing.sm,
                  ),
                  child: Container(
                    padding: const EdgeInsets.all(AppSpacing.sm),
                    decoration: BoxDecoration(
                      color: AppColors.warningSoft,
                      borderRadius: AppRadii.control,
                      border: Border.all(
                        color: AppColors.warning.withValues(alpha: 0.35),
                      ),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        const Icon(
                          Icons.info_outline_rounded,
                          size: AppSizes.iconSmall,
                          color: AppColors.warning,
                        ),
                        const SizedBox(width: AppSpacing.xs),
                        Expanded(
                          child: Text(
                            materialWarning,
                            style: const TextStyle(
                              color: AppColors.warning,
                              fontSize: 13,
                              fontWeight: FontWeight.w500,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),
              ],
              _informationRow(
                Icons.wb_sunny_outlined,
                'Best time to visit',
                bestTime,
              ),
              _informationRow(Icons.payments_outlined, 'Price level', price),
              _informationRow(Icons.phone_outlined, 'Contact', phone),
              _informationRow(Icons.language_outlined, 'Website', website),
            ],
          ),
        ),
      ],
    );
  }

  Widget _reviewCard(Map<String, dynamic> review) {
    final author = _reviewAuthor(review);
    final body = _text(
      review['description'] ?? review['text'] ?? review['snippet'],
    );
    final date = _text(review['date'] ?? review['relative_date']);
    final reviewRating = num.tryParse('${review['rating'] ?? ''}');
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              CircleAvatar(
                backgroundColor: AppColors.primarySoft,
                child: Text(author.isEmpty ? 'T' : author[0].toUpperCase()),
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(author, style: Theme.of(context).textTheme.titleSmall),
                    if (date.isNotEmpty)
                      Text(
                        date,
                        style: Theme.of(context)
                            .textTheme
                            .bodySmall
                            ?.copyWith(color: AppColors.textSecondary),
                      ),
                  ],
                ),
              ),
              if (reviewRating != null && reviewRating > 0)
                Semantics(
                  label: '$reviewRating out of 5 stars',
                  child: StatusChip(
                    text: '$reviewRating',
                    icon: Icons.star_rounded,
                    tone: AppStatusTone.neutral,
                  ),
                ),
            ],
          ),
          if (body.isNotEmpty) ...[
            const SizedBox(height: AppSpacing.sm),
            Text(body),
          ],
        ],
      ),
    );
  }

  Widget _reviewsSection() {
    final reviews = _reviews();
    final visible = showAllReviews ? reviews : reviews.take(3).toList();
    final privatePreview = reviewInfo?['fypPreview'] == true;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        AppSectionHeader(
          title: 'Local Reviews',
          subtitle: reviewInfo?['rating'] == null ? 'TravelMate community reviews' : null,
        ),
        if (reviewInfo?['rating'] != null)
          Padding(
            padding: const EdgeInsets.only(top: AppSpacing.xs),
            child: LocalReviewRatingBadge(summary: reviewInfo!),
          ),
        if (privatePreview)
          Text(hasLocalSampleReviews
              ? 'FYP sample reviews · fictional demonstration content'
              : 'Fictional reviews for the private FYP demonstration.'),
        if (hasLocalSampleReviews || sampleReviews)
          TertiaryButton(
            label: sampleReviews ? 'View community reviews' : 'View FYP sample reviews',
            onPressed: loading ? null : () {
              sampleReviews = !sampleReviews;
              showAllReviews = false;
              loadDetails();
            },
          )
        else if (privatePreview || (communityReviews && hasPrivateReviewPreview))
          TertiaryButton(
            label: communityReviews ? 'Back to private FYP preview' : 'View community reviews',
            onPressed: loading ? null : () {
              communityReviews = !communityReviews;
              showAllReviews = false;
              loadDetails();
            },
          ),
        const SizedBox(height: AppSpacing.sm),
        if (reviewsFailed)
          AppErrorState(
            title: 'Reviews couldn’t be loaded',
            message: 'The place details are still available.',
            onRetry: loadDetails,
          )
        else if (reviews.isEmpty)
          const TravelEmptyState(
            icon: Icons.rate_review_outlined,
            title: 'No TravelMate reviews yet.',
            message: 'Be the first to share your experience of this place.',
          )
        else ...[
          ...visible.map(
            (review) => Padding(
              padding: const EdgeInsets.only(bottom: AppSpacing.xs),
              child: _reviewCard(review),
            ),
          ),
          if (reviews.length > 3)
            Align(
              alignment: Alignment.centerLeft,
              child: TertiaryButton(
                label: showAllReviews
                    ? 'Show fewer reviews'
                    : 'View all ${reviews.length} reviews',
                onPressed: () =>
                    setState(() => showAllReviews = !showAllReviews),
              ),
            ),
        ],
        const SizedBox(height: AppSpacing.xs),
        if (!privatePreview && !sampleReviews) SecondaryButton(
          label: 'Write a review',
          icon: Icons.rate_review_outlined,
          onPressed: () async { await Navigator.push(
            context,
            MaterialPageRoute(
              builder: (_) => FeedbackScreen(
                initialDestination: {...detail, 'destinationId': reviewDestinationId},
                api: api,
              ),
            ),
          ); if (mounted) await loadDetails(); },
        ),
      ],
    );
  }

  Widget _nearbySection() => Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const AppSectionHeader(
            title: 'Nearby places',
            subtitle: 'More places that may fit the same day.',
          ),
          const SizedBox(height: AppSpacing.sm),
          if (nearbyFailed)
            AppErrorState(
              title: 'Nearby places couldn’t be loaded',
              message: 'You can still use the rest of this page.',
              onRetry: loadDetails,
            )
          else if (nearbyPlaces.isEmpty)
            const TravelEmptyState(
              icon: Icons.near_me_outlined,
              title: 'No nearby places yet',
              message:
                  'Nearby suggestions will appear when location data is available.',
            )
          else
            ...nearbyPlaces.take(3).map(
                  (place) => Padding(
                    padding: const EdgeInsets.only(bottom: AppSpacing.sm),
                    child: DestinationCard(
                      destination: place,
                      compact: true,
                      onView: () => Navigator.push(
                        context,
                        MaterialPageRoute(
                          builder: (_) => DestinationDetailsScreen(
                            initialDestination: place,
                            api: api,
                          ),
                        ),
                      ),
                      onAddToTrip: adding ? null : () => addToItinerary(place),
                    ),
                  ),
                ),
        ],
      );

  @override
  Widget build(BuildContext context) {
    if (!loading && detailsFailed && !_hasEssentialDetails) {
      return TravelMatePageScaffold(
        appBar: AppBar(title: const Text('Destination details')),
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.lg),
            child: AppErrorState(
              title: 'Destination details unavailable',
              message:
                  'We couldn’t load the details for this destination. Please check your connection and try again.',
              onRetry: loadDetails,
            ),
          ),
        ),
      );
    }

    final description =
        _text(detail['description'] ?? detail['snippet'] ?? detail['about']);
    final reasons = _personalReasons();

    return TravelMatePageScaffold(
      appBar: AppBar(
        title: const Text('Destination details'),
        actions: [
          IconButton(
            tooltip: 'Refresh destination',
            onPressed: loading ? null : loadDetails,
            icon: const Icon(Icons.refresh_rounded),
          ),
        ],
      ),
      padding: EdgeInsets.zero,
      bottomNavigationBar: SafeArea(
        top: false,
        child: Container(
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            AppSpacing.sm,
            AppSpacing.md,
            AppSpacing.sm,
          ),
          decoration: const BoxDecoration(
            color: AppColors.surface,
            border: Border(top: BorderSide(color: AppColors.divider)),
          ),
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            if (favourites.error != null) TextButton(onPressed: favourites.load, child: Text(favourites.error!)),
            Row(
            children: [
              Expanded(
                child: Semantics(
                  key: const ValueKey('destination-save'),
                  button: true,
                  toggled: saved,
                  label: saved ? 'Destination saved. Tap to remove favourite' : 'Save destination',
                  child: OutlinedButton.icon(
                    label: Text(saved ? 'Saved' : (saving ? 'Saving…' : 'Save')),
                    icon: Icon(saved ? Icons.favorite_rounded : Icons.favorite_border_rounded, color: saved ? Colors.red : null),
                    onPressed: saving || !favourites.loaded || favourites.error != null ? null : saveFavourite,
                  ),
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                flex: 2,
                child: PrimaryButton(
                  key: const ValueKey('destination-primary-add'),
                  label: adding ? 'Adding…' : 'Add to trip',
                  icon: Icons.add_location_alt_outlined,
                  onPressed: adding ? null : addToItinerary,
                ),
              ),
            ],
          ),
          ]),
        ),
      ),
      body: RefreshIndicator(
        onRefresh: loadDetails,
        child: ListView(
          key: const ValueKey('destination-details-scroll'),
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            AppSpacing.xs,
            AppSpacing.md,
            AppSpacing.xxl,
          ),
          children: [
            if (loading) ...[
              const LinearProgressIndicator(),
              const SizedBox(height: AppSpacing.sm),
            ],
            _hero(),
            if (reasons.isNotEmpty) ...[
              const SizedBox(height: AppSpacing.lg),
              _personalContext(),
            ],
            const SizedBox(height: AppSpacing.lg),
            const AppSectionHeader(title: 'About'),
            const SizedBox(height: AppSpacing.sm),
            InkCard(child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(description.isNotEmpty ? description : 'A detailed description is not available from this source.'),
              if (category.isNotEmpty) Text('Category: $category'),
              if (address.isNotEmpty) Text('Location: $address'),
              for (final highlight in (detail['highlights'] as List? ?? []).whereType<String>()) Text('• $highlight'),
            ])),
            const SizedBox(height: AppSpacing.lg),
            _visitInformation(),
            const SizedBox(height: AppSpacing.lg),
            _reviewsSection(),
            const SizedBox(height: AppSpacing.lg),
            _nearbySection(),
          ],
        ),
      ),
    );
  }
}
