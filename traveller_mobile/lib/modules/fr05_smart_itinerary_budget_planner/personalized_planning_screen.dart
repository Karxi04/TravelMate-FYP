import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../fr02_travel_preference/preferences_screen.dart';
import 'trip_details_screen.dart';

class PersonalizedPlanningScreen extends StatefulWidget {
  final ApiService? api;

  const PersonalizedPlanningScreen({super.key, this.api});

  @override
  State<PersonalizedPlanningScreen> createState() =>
      _PersonalizedPlanningScreenState();
}

class _PersonalizedPlanningScreenState
    extends State<PersonalizedPlanningScreen> {
  late final ApiService api;
  final destination = TextEditingController(text: 'Penang, Malaysia');
  final travellers = TextEditingController(text: '1');
  final budget = TextEditingController(text: '1200');
  final origin = TextEditingController();
  String travelMode = 'undecided';
  String accommodationChoice = 'undecided';
  String carRentalChoice = 'undecided';
  late final TextEditingController startDate;
  late final TextEditingController endDate;

  Map<String, dynamic> preferences = {};
  List<Map<String, dynamic>> recommendations = [];
  final Set<String> touchedFields = {};

  bool profileLoading = true;
  bool suggestionsLoading = true;
  bool generating = false;
  bool showValidationErrors = false;
  bool snapshotConflict = false;
  String? profileError;
  String? suggestionsError;
  String recommendationSource = '';
  String snapshotDestination = '';
  String? recommendationGenerationId;
  String? generationRequestId;
  String? generationSignature;
  String? completedTripId;
  String? failedTripId;
  String? failureMessage;
  bool retryable = false;

  String dateText(DateTime date) =>
      '${date.year.toString().padLeft(4, '0')}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    final start = DateTime.now().add(const Duration(days: 30));
    startDate = TextEditingController(text: dateText(start));
    endDate = TextEditingController(
      text: dateText(start.add(const Duration(days: 2))),
    );
    Future.microtask(_loadInitialData);
  }

  @override
  void dispose() {
    destination.dispose();
    travellers.dispose();
    budget.dispose();
    origin.dispose();
    startDate.dispose();
    endDate.dispose();
    super.dispose();
  }

  Future<void> _loadInitialData() async {
    await Future.wait([
      _loadProfile(),
      _loadSuggestions(regenerate: false),
    ]);
  }

  Future<void> _loadProfile() async {
    if (mounted) {
      setState(() {
        profileLoading = true;
        profileError = null;
      });
    }
    try {
      final data = await api.get('/api/fr2/preferences');
      if (!mounted) return;
      final raw = data is Map ? data['preferences'] : null;
      setState(() {
        preferences = raw is Map ? Map<String, dynamic>.from(raw) : {};
        profileError = preferences.isEmpty
            ? 'Complete your travel preferences before building a personalised trip.'
            : null;
      });
    } catch (_) {
      if (mounted) {
        setState(() => profileError = 'We could not load your travel style.');
      }
    } finally {
      if (mounted) setState(() => profileLoading = false);
    }
  }

  String _normaliseDestination(String value) =>
      value.trim().toLowerCase().replaceAll(RegExp(r'\s+'), ' ');

  bool get _snapshotMatchesDestination =>
      snapshotDestination.isNotEmpty &&
      _normaliseDestination(snapshotDestination) ==
          _normaliseDestination(destination.text);

  bool get _snapshotReady =>
      recommendationGenerationId?.isNotEmpty == true &&
      recommendations.isNotEmpty &&
      _snapshotMatchesDestination &&
      !snapshotConflict;

  void _clearGenerationState() {
    generationRequestId = null;
    generationSignature = null;
    completedTripId = null;
    failedTripId = null;
    failureMessage = null;
    retryable = false;
  }

  void _clearSnapshot() {
    recommendationGenerationId = null;
    snapshotDestination = '';
    recommendationSource = '';
    recommendations = [];
    snapshotConflict = false;
    suggestionsError = null;
    _clearGenerationState();
  }

  void _onFieldChanged(String field, {bool destinationChanged = false}) {
    setState(() {
      touchedFields.add(field);
      if (destinationChanged) {
        _clearSnapshot();
      } else {
        _clearGenerationState();
      }
    });
  }

  Map<String, String> _validationErrors() {
    final errors = <String, String>{};
    if (destination.text.trim().isEmpty) {
      errors['destination'] = 'Choose a destination.';
    }
    final start = DateTime.tryParse(startDate.text.trim());
    final end = DateTime.tryParse(endDate.text.trim());
    if (start == null) errors['startDate'] = 'Choose a valid start date.';
    if (end == null) {
      errors['endDate'] = 'Choose a valid end date.';
    } else if (start != null && end.isBefore(start)) {
      errors['endDate'] = 'End date must be on or after start date.';
    }
    final count = int.tryParse(travellers.text.trim());
    if (count == null || count < 1) {
      errors['travellers'] = 'Enter at least 1 traveller.';
    }
    final limit = double.tryParse(budget.text.trim());
    if (limit == null || limit < 0) {
      errors['budget'] = 'Enter a valid non-negative budget.';
    }
    return errors;
  }

  String? _fieldError(String field) {
    if (!showValidationErrors && !touchedFields.contains(field)) return null;
    return _validationErrors()[field];
  }

  Future<void> _pickDate(
    TextEditingController controller,
    String field,
  ) async {
    final initial = DateTime.tryParse(controller.text) ??
        DateTime.now().add(const Duration(days: 30));
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime.now().subtract(const Duration(days: 1)),
      lastDate: DateTime.now().add(const Duration(days: 730)),
    );
    if (picked == null || !mounted) return;
    setState(() {
      controller.text = dateText(picked);
      touchedFields.add(field);
      _clearGenerationState();
    });
  }

  Future<void> _loadSuggestions({required bool regenerate}) async {
    if (suggestionsLoading && regenerate) return;
    final requestedDestination = destination.text.trim();
    if (requestedDestination.isEmpty) {
      if (mounted) {
        setState(() {
          touchedFields.add('destination');
          suggestionsLoading = false;
        });
      }
      return;
    }
    if (mounted) {
      setState(() {
        suggestionsLoading = true;
        suggestionsError = null;
        if (regenerate) _clearGenerationState();
      });
    }

    try {
      final dynamic data = regenerate
          ? await api.post('/api/fr4/recommendations/generate', {
              'destinationArea': requestedDestination,
            })
          : await api.get('/api/fr4/recommendations', {
              'destinationArea': requestedDestination,
            });
      if (!mounted || data is! Map) return;

      final items = (data['recommendations'] as List? ?? const [])
          .whereType<Map>()
          .map((item) => Map<String, dynamic>.from(item))
          .toList();
      final rawSnapshot = data['snapshot'];
      final snapshot = rawSnapshot is Map
          ? Map<String, dynamic>.from(rawSnapshot)
          : <String, dynamic>{};
      final generationId =
          (data['recommendationGenerationId'] ?? '').toString().trim();
      final storedDestination = (snapshot['requestedDestination'] ??
              snapshot['destinationArea'] ??
              requestedDestination)
          .toString()
          .trim();

      setState(() {
        recommendations = items;
        recommendationGenerationId =
            generationId.isEmpty || items.isEmpty ? null : generationId;
        snapshotDestination = items.isEmpty ? '' : storedDestination;
        recommendationSource =
            (data['source'] ?? snapshot['source'] ?? '').toString().trim();
        snapshotConflict = false;
        suggestionsError = items.isEmpty
            ? 'No saved suggestions are available for this destination yet.'
            : null;
      });
    } on ApiException catch (error) {
      if (!mounted) return;
      setState(() {
        suggestionsError = error.statusCode == 404
            ? 'No saved suggestions are available for this destination yet.'
            : 'We could not load suggestions for this destination.';
      });
    } catch (_) {
      if (mounted) {
        setState(() {
          suggestionsError =
              'We could not load suggestions for this destination.';
        });
      }
    } finally {
      if (mounted) setState(() => suggestionsLoading = false);
    }
  }

  String get _derivedTitle {
    final area = destination.text.trim().split(',').first.trim();
    return area.isEmpty ? 'My Personalised Trip' : 'My Personalised $area Trip';
  }

  String get _inputSignature => [
        _derivedTitle,
        _normaliseDestination(destination.text),
        startDate.text.trim(),
        endDate.text.trim(),
        travellers.text.trim(),
        budget.text.trim(),
        origin.text.trim(),
        travelMode,
        accommodationChoice,
        carRentalChoice,
        recommendationGenerationId ?? '',
      ].join('|');

  Map<String, dynamic> _tripPayload() => {
        'title': _derivedTitle,
        'destinationArea': destination.text.trim(),
        'destinationName': destination.text.trim(),
        'startDate': startDate.text.trim(),
        'endDate': endDate.text.trim(),
        'travellerCount': int.parse(travellers.text.trim()),
        'budgetLimit': double.parse(budget.text.trim()),
        if (origin.text.trim().isNotEmpty) 'originLocation': origin.text.trim(),
        'travelMode': travelMode,
        'accommodationChoice': accommodationChoice,
        'carRentalChoice': carRentalChoice,
        'recommendationGenerationId': recommendationGenerationId,
        'generationRequestId': generationRequestId,
      };

  Future<void> _openTrip(String tripId) async {
    await Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => TripDetailsScreen(tripId: tripId, api: api),
      ),
    );
  }

  String _failureCopy(String stage, {required bool hasDraft}) {
    if (stage == 'trip_creation') {
      return 'We couldn\'t create your trip. Please try again.';
    }
    if (stage == 'budget_calculation') {
      return hasDraft
          ? 'We couldn\'t finish the budget. Your trip draft is safe and you can try again.'
          : 'We couldn\'t finish the budget. Please try again.';
    }
    return hasDraft
        ? 'We couldn\'t finish your itinerary. Your trip draft is safe and you can try again.'
        : 'We couldn\'t finish your itinerary. Please try again.';
  }

  void _recordFailure(
    Map<String, dynamic> data, {
    bool transportFailure = false,
  }) {
    final id = (data['tripId'] ?? data['id'] ?? '').toString().trim();
    failedTripId = id.isEmpty ? null : id;
    final stage = (data['stage'] ?? 'trip_generation').toString();
    retryable = data['retryable'] == true ||
        (transportFailure && generationRequestId != null);
    failureMessage = _failureCopy(stage, hasDraft: failedTripId != null);
  }

  Future<void> _buildPlan({bool retry = false}) async {
    if (generating) return;
    FocusScope.of(context).unfocus();
    setState(() => showValidationErrors = true);
    if (_validationErrors().isNotEmpty) return;
    if (!_snapshotReady) {
      setState(() {
        suggestionsError = snapshotConflict
            ? 'Refresh suggestions for this destination before building your itinerary.'
            : 'Load suggestions for this destination before building your itinerary.';
      });
      return;
    }

    final signature = _inputSignature;
    if (generationSignature != signature) {
      generationSignature = signature;
      generationRequestId =
          'personalised_${DateTime.now().microsecondsSinceEpoch}';
      completedTripId = null;
      failedTripId = null;
    }
    if (!retry && completedTripId != null) {
      await _openTrip(completedTripId!);
      return;
    }

    setState(() {
      generating = true;
      failureMessage = null;
      retryable = false;
    });
    try {
      final generated = await api.post(
        '/api/fr5/personalised-trips/generate',
        _tripPayload(),
      );
      if (generated is! Map || generated['ok'] != true) {
        final data = generated is Map
            ? Map<String, dynamic>.from(generated)
            : <String, dynamic>{};
        if (mounted) setState(() => _recordFailure(data));
        return;
      }
      final tripId =
          (generated['tripId'] ?? generated['id'] ?? '').toString().trim();
      if (tripId.isEmpty) {
        if (mounted) setState(() => _recordFailure(const {}));
        return;
      }
      if (generated['status'] != 'planned') {
        if (mounted) {
          setState(() => _recordFailure({
                ...Map<String, dynamic>.from(generated),
                'stage': generated['stage'] ?? 'trip_generation',
                'retryable': generated['retryable'] ?? true,
              }));
        }
        return;
      }
      completedTripId = tripId;
      failedTripId = null;
      if (!mounted) return;
      await _openTrip(tripId);
    } on ApiException catch (error) {
      if (!mounted) return;
      if (error.statusCode == 409) {
        setState(() {
          snapshotConflict = true;
          retryable = false;
          failureMessage =
              'Your recommendations are out of date. Refresh suggestions for this destination and try again.';
        });
      } else {
        setState(() => _recordFailure(error.data));
      }
    } catch (_) {
      if (mounted) {
        setState(() => _recordFailure(const {}, transportFailure: true));
      }
    } finally {
      if (mounted) setState(() => generating = false);
    }
  }

  Future<void> _adjustPreferences() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => const PreferencesScreen()),
    );
    if (!mounted) return;
    await _loadProfile();
    if (!mounted) return;
    setState(() {
      _clearSnapshot();
      suggestionsError =
          'Refresh suggestions to use your updated travel preferences.';
    });
  }

  List<String> get _interests => (preferences['interests'] as List? ?? const [])
      .map((value) => value.toString().trim())
      .where((value) => value.isNotEmpty)
      .toList();

  Widget _sectionLabel(int number, String title, String subtitle) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        CircleAvatar(
          radius: 16,
          backgroundColor: AppColors.primarySoft,
          foregroundColor: AppColors.primaryStrong,
          child: Text('$number'),
        ),
        const SizedBox(width: AppSpacing.sm),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: Theme.of(context).textTheme.titleLarge),
              const SizedBox(height: AppSpacing.xxs),
              Text(
                subtitle,
                style: Theme.of(context).textTheme.bodySmall?.copyWith(
                      color: AppColors.textSecondary,
                    ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _tripBasics() {
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionLabel(
            1,
            'Trip basics',
            'Tell us where, when and who this trip is for.',
          ),
          const SizedBox(height: AppSpacing.md),
          AppTextField(
            key: const ValueKey('planning-destination'),
            controller: destination,
            label: 'Where are you going?',
            hint: 'Penang, Malaysia',
            prefixIcon: Icons.location_on_outlined,
            errorText: _fieldError('destination'),
            textInputAction: TextInputAction.next,
            onChanged: (_) =>
                _onFieldChanged('destination', destinationChanged: true),
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: AppTextField(
                  key: const ValueKey('planning-start-date'),
                  controller: startDate,
                  label: 'Start date',
                  prefixIcon: Icons.calendar_month_outlined,
                  errorText: _fieldError('startDate'),
                  readOnly: true,
                  onTap: () => _pickDate(startDate, 'startDate'),
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: AppTextField(
                  key: const ValueKey('planning-end-date'),
                  controller: endDate,
                  label: 'End date',
                  prefixIcon: Icons.event_outlined,
                  errorText: _fieldError('endDate'),
                  readOnly: true,
                  onTap: () => _pickDate(endDate, 'endDate'),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.sm),
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: AppTextField(
                  key: const ValueKey('planning-travellers'),
                  controller: travellers,
                  label: 'Travellers',
                  prefixIcon: Icons.people_outline_rounded,
                  errorText: _fieldError('travellers'),
                  keyboardType: TextInputType.number,
                  inputFormatters: [FilteringTextInputFormatter.digitsOnly],
                  textInputAction: TextInputAction.next,
                  onChanged: (_) => _onFieldChanged('travellers'),
                ),
              ),
              const SizedBox(width: AppSpacing.xs),
              Expanded(
                child: AppTextField(
                  key: const ValueKey('planning-budget'),
                  controller: budget,
                  label: 'Budget (RM)',
                  prefixIcon: Icons.account_balance_wallet_outlined,
                  errorText: _fieldError('budget'),
                  keyboardType: const TextInputType.numberWithOptions(
                    decimal: true,
                  ),
                  inputFormatters: [
                    FilteringTextInputFormatter.allow(
                        RegExp(r'^\d*\.?\d{0,2}')),
                  ],
                  textInputAction: TextInputAction.done,
                  onChanged: (_) => _onFieldChanged('budget'),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          const Text(
              'One total MYR budget for the whole group, including applicable travel and accommodation costs.'),
        ],
      ),
    );
  }

  Widget _arrangementChoices(String field, String label, String value,
      Map<String, String> options, ValueChanged<String> onChanged) {
    return Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
      Text(label, style: Theme.of(context).textTheme.titleSmall),
      const SizedBox(height: AppSpacing.xs),
      Wrap(
        spacing: AppSpacing.xs,
        runSpacing: AppSpacing.xs,
        children: options.entries
            .map((entry) => ChoiceChip(
                  key: ValueKey('planning-$field-${entry.key}'),
                  label: Text(entry.value),
                  selected: value == entry.key,
                  onSelected: generating
                      ? null
                      : (_) {
                          setState(() {
                            onChanged(entry.key);
                            _clearGenerationState();
                          });
                        },
                ))
            .toList(),
      ),
      const SizedBox(height: AppSpacing.sm),
    ]);
  }

  Widget _travelArrangements() {
    return InkCard(
        child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _sectionLabel(2, 'Travel arrangements',
            'Choose what applies. Not decided is different from not needed.'),
        const SizedBox(height: AppSpacing.md),
        AppTextField(
          key: const ValueKey('planning-origin'),
          controller: origin,
          label: 'Departure location (optional)',
          hint: 'e.g. Bukit Mertajam, Penang',
          prefixIcon: Icons.trip_origin,
          readOnly: generating,
          onChanged: (_) => _onFieldChanged('origin'),
        ),
        const SizedBox(height: AppSpacing.md),
        _arrangementChoices(
            'travel-mode',
            'Intercity travel',
            travelMode,
            const {
              'undecided': 'Not decided',
              'flight': 'Flight',
              'own_vehicle': 'Own vehicle',
              'public_transport': 'Public transport',
              'other': 'Other',
            },
            (value) => travelMode = value),
        if (travelMode == 'own_vehicle')
          const Text('Fuel and tolls are outside the current budget estimate.'),
        if (travelMode == 'public_transport' || travelMode == 'other')
          const Text(
              'Intercity fares are outside the current budget estimate.'),
        if (travelMode == 'flight')
          const Text(
              'Flight intent only. A flight price is still needed; no ticket is booked.'),
        const SizedBox(height: AppSpacing.sm),
        _arrangementChoices(
            'accommodation',
            'Accommodation',
            accommodationChoice,
            const {
              'undecided': 'Not decided',
              'paid_hotel': 'Paid hotel',
              'staying_with_family': 'Family / friends',
              'return_home': 'Return home',
              'other': 'Other',
            },
            (value) => accommodationChoice = value),
        if (accommodationChoice == 'paid_hotel')
          const Text(
              'A hotel price is still needed. This choice does not book a room.'),
        if (accommodationChoice == 'other')
          const Text(
              'Other accommodation costs are outside the current budget estimate.'),
        const SizedBox(height: AppSpacing.sm),
        _arrangementChoices(
            'rental',
            'Car rental at destination',
            carRentalChoice,
            const {
              'undecided': 'Not decided',
              'selected': 'Want to rent',
              'not_required': 'Not needed',
            },
            (value) => carRentalChoice = value),
        if (carRentalChoice == 'selected')
          const Text(
              'Rental intent only; no quote or reservation is attached. The current rental catalogue uses simulated prices.'),
      ],
    ));
  }

  Widget _profileSummary() {
    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionLabel(
            3,
            'Your travel style',
            'TravelMate uses your saved profile to personalise this trip.',
          ),
          const SizedBox(height: AppSpacing.md),
          if (profileLoading)
            const AppLoadingState(message: 'Loading your travel style…')
          else if (profileError != null)
            AppErrorState(
              title: 'Travel style unavailable',
              message: profileError!,
              retryLabel: 'Try again',
              onRetry: _loadProfile,
            )
          else ...[
            Semantics(
              container: true,
              label: 'Planning for your saved travel style',
              child: Container(
                width: double.infinity,
                padding: AppSpacing.card,
                decoration: BoxDecoration(
                  color: AppColors.primarySoft,
                  borderRadius: AppRadii.control,
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      (preferences['travelPersonality'] ??
                              preferences['travelType'] ??
                              'Your travel style')
                          .toString(),
                      style: Theme.of(context).textTheme.titleLarge,
                    ),
                    const SizedBox(height: AppSpacing.xs),
                    Wrap(
                      spacing: AppSpacing.xs,
                      runSpacing: AppSpacing.xs,
                      children: [
                        ..._interests.take(3).map(
                              (interest) => StatusChip(
                                text: interest,
                                tone: AppStatusTone.neutral,
                              ),
                            ),
                        if ((preferences['travelPace'] ?? '')
                            .toString()
                            .trim()
                            .isNotEmpty)
                          StatusChip(
                            text: '${preferences['travelPace']} pace',
                            tone: AppStatusTone.neutral,
                          ),
                        if ((preferences['budgetRange'] ?? '')
                            .toString()
                            .trim()
                            .isNotEmpty)
                          StatusChip(
                            text: '${preferences['budgetRange']} budget',
                            tone: AppStatusTone.neutral,
                          ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            TertiaryButton(
              label: 'Adjust preferences',
              icon: Icons.tune_rounded,
              onPressed: generating ? null : _adjustPreferences,
            ),
          ],
        ],
      ),
    );
  }

  num? _score(Map<String, dynamic> item) {
    final value = item['finalScore'] ?? item['score'];
    if (value is num) return value.clamp(0, 100);
    return num.tryParse((value ?? '').toString())?.clamp(0, 100);
  }

  List<String> _reasons(Map<String, dynamic> item) {
    final reasons = item['matchReasons'];
    if (reasons is List) {
      return reasons
          .map((value) => value.toString().trim())
          .where((value) => value.isNotEmpty)
          .take(2)
          .toList();
    }
    final reason = (item['recommendationReason'] ?? item['reason'] ?? '')
        .toString()
        .trim();
    if (reason.isEmpty) return const [];
    return reason
        .split('•')
        .map((value) => value.trim())
        .where((value) =>
            value.isNotEmpty &&
            !RegExp(r'^\d+(\.\d+)?%\s*match$', caseSensitive: false)
                .hasMatch(value))
        .take(2)
        .toList();
  }

  Widget _suggestionTile(Map<String, dynamic> item, int index) {
    final title =
        (item['title'] ?? item['name'] ?? 'Recommended place').toString();
    final score = _score(item);
    final reasons = _reasons(item);
    return Padding(
      padding: EdgeInsets.only(top: index == 0 ? 0 : AppSpacing.xs),
      child: Semantics(
        container: true,
        selected: true,
        label: '$title, selected for your trip',
        child: Container(
          padding: AppSpacing.card,
          decoration: BoxDecoration(
            color: AppColors.surfaceElevated,
            border: Border.all(color: AppColors.divider),
            borderRadius: AppRadii.control,
          ),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.check_circle_rounded,
                color: AppColors.success,
                semanticLabel: 'Selected',
              ),
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Text(
                            title,
                            style: Theme.of(context).textTheme.titleMedium,
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
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      reasons.isEmpty
                          ? 'Recommended for your saved travel style.'
                          : reasons.join(' · '),
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textSecondary,
                          ),
                    ),
                    const SizedBox(height: AppSpacing.xxs),
                    Text(
                      'Selected for planning',
                      style: Theme.of(context).textTheme.labelMedium?.copyWith(
                            color: AppColors.success,
                          ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _suggestionsReview() {
    return InkCard(
      key: recommendationGenerationId == null
          ? const ValueKey('planning-snapshot-empty')
          : ValueKey('planning-snapshot-$recommendationGenerationId'),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          _sectionLabel(
            4,
            'Suggestions for this trip',
            'These places come from one saved recommendation set for your destination.',
          ),
          const SizedBox(height: AppSpacing.md),
          if (suggestionsLoading)
            AppLoadingState(
              message: 'Loading suggestions for ${destination.text.trim()}…',
            )
          else if (_snapshotReady) ...[
            Row(
              children: [
                Expanded(
                  child: Text(
                    'Selected for your trip',
                    style: Theme.of(context).textTheme.titleMedium,
                  ),
                ),
                StatusChip(
                  text: '${recommendations.length} places',
                  icon: Icons.check_rounded,
                  tone: AppStatusTone.success,
                ),
              ],
            ),
            if (recommendationSource.isNotEmpty &&
                !{'live', 'provider', 'live_provider', 'serpapi'}
                    .contains(recommendationSource.toLowerCase())) ...[
              const SizedBox(height: AppSpacing.xs),
              SourceFallbackBadge(source: recommendationSource),
            ],
            const SizedBox(height: AppSpacing.sm),
            ...recommendations.indexed.map(
              (entry) => _suggestionTile(entry.$2, entry.$1),
            ),
            const SizedBox(height: AppSpacing.sm),
            SecondaryButton(
              label: 'Refresh suggestions',
              icon: Icons.refresh_rounded,
              onPressed:
                  generating ? null : () => _loadSuggestions(regenerate: true),
            ),
          ] else ...[
            AppErrorState(
              title: snapshotConflict
                  ? 'Your recommendations are out of date'
                  : 'Suggestions needed',
              message: snapshotConflict
                  ? failureMessage ??
                      'Refresh suggestions for this destination and try again.'
                  : suggestionsError ??
                      'Find personalised places for this destination before building your itinerary.',
              retryLabel:
                  snapshotConflict ? 'Refresh suggestions' : 'Find suggestions',
              onRetry:
                  generating ? null : () => _loadSuggestions(regenerate: true),
            ),
          ],
        ],
      ),
    );
  }

  Widget _generationProgress() {
    return Semantics(
      liveRegion: true,
      label: 'Building your itinerary',
      child: InkCard(
        color: AppColors.infoSoft,
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                const SizedBox.square(
                  dimension: AppSizes.icon,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
                const SizedBox(width: AppSpacing.sm),
                Expanded(
                  child: Text(
                    'Building your ${destination.text.trim().split(',').first} trip',
                    style: Theme.of(context).textTheme.titleLarge,
                  ),
                ),
              ],
            ),
            const SizedBox(height: AppSpacing.sm),
            const _ProgressLine(
              label: 'Travel preferences matched',
              complete: true,
            ),
            const _ProgressLine(
              label: 'Recommendations selected',
              complete: true,
            ),
            const _ProgressLine(
              label: 'Arranging your itinerary and budget',
              complete: false,
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'We’re arranging activities around your dates, travel pace, location and budget.',
              style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                    color: AppColors.textSecondary,
                  ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _failureState() {
    final conflict = snapshotConflict;
    return AppErrorState(
      title: conflict
          ? 'Your recommendations are out of date'
          : 'We couldn’t finish your itinerary',
      message: failureMessage ?? 'Please try again.',
      retryLabel: conflict ? 'Refresh suggestions' : 'Retry this trip',
      onRetry: conflict
          ? () => _loadSuggestions(regenerate: true)
          : retryable && recommendationGenerationId != null
              ? () => _buildPlan(retry: true)
              : null,
    );
  }

  @override
  Widget build(BuildContext context) {
    return TravelMatePageScaffold(
      appBar: AppBar(title: const Text('Plan a trip')),
      padding: EdgeInsets.zero,
      body: GestureDetector(
        behavior: HitTestBehavior.translucent,
        onTap: () => FocusScope.of(context).unfocus(),
        child: ListView(
          keyboardDismissBehavior: ScrollViewKeyboardDismissBehavior.onDrag,
          padding: const EdgeInsets.fromLTRB(
            AppSpacing.md,
            AppSpacing.xs,
            AppSpacing.md,
            AppSpacing.xxl,
          ),
          children: [
            const AppSectionHeader(
              title: 'Build a trip around you',
              subtitle:
                  'Set your trip basics, review what TravelMate will use, then build your itinerary.',
            ),
            const SizedBox(height: AppSpacing.md),
            _tripBasics(),
            const SizedBox(height: AppSpacing.md),
            _travelArrangements(),
            const SizedBox(height: AppSpacing.md),
            _profileSummary(),
            const SizedBox(height: AppSpacing.md),
            _suggestionsReview(),
            if (generating) ...[
              const SizedBox(height: AppSpacing.md),
              _generationProgress(),
            ],
            if (failureMessage != null && !snapshotConflict) ...[
              const SizedBox(height: AppSpacing.md),
              _failureState(),
            ],
            const SizedBox(height: AppSpacing.lg),
            Semantics(
              button: true,
              enabled: _snapshotReady && !generating,
              label:
                  generating ? 'Building your itinerary' : 'Build my itinerary',
              child: PrimaryButton(
                key: const ValueKey('build-itinerary-button'),
                label: 'Build my itinerary',
                icon: Icons.auto_awesome_rounded,
                loading: generating,
                onPressed: _snapshotReady && !generating ? _buildPlan : null,
              ),
            ),
            const SizedBox(height: AppSpacing.xs),
            Text(
              'TravelMate will create a day-by-day plan and estimate the budget using the selected suggestions.',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.bodySmall?.copyWith(
                    color: AppColors.textSecondary,
                  ),
            ),
          ],
        ),
      ),
    );
  }
}

class _ProgressLine extends StatelessWidget {
  final String label;
  final bool complete;

  const _ProgressLine({required this.label, required this.complete});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: AppSpacing.xxs),
      child: Row(
        children: [
          Icon(
            complete ? Icons.check_circle_rounded : Icons.more_horiz_rounded,
            size: AppSizes.iconSmall,
            color: complete ? AppColors.success : AppColors.info,
          ),
          const SizedBox(width: AppSpacing.xs),
          Expanded(child: Text(label)),
        ],
      ),
    );
  }
}
