import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class PreferencesScreen extends StatefulWidget {
  final bool onboarding;
  final VoidCallback? onCompleted;
  final ApiService? api;
  final bool loadExisting;

  const PreferencesScreen({
    super.key,
    this.onboarding = false,
    this.onCompleted,
    this.api,
    this.loadExisting = true,
  });

  @override
  State<PreferencesScreen> createState() => _PreferencesScreenState();
}

class _PreferencesScreenState extends State<PreferencesScreen> {
  late final ApiService api;
  final PageController controller = PageController();

  int page = 0;
  bool busy = false;
  bool loading = true;
  String? loadError;

  String personality = 'Balanced';
  String sleepingType = 'Flexible';
  String travelType = 'Mixed';
  String budget = 'Moderate';
  String pace = 'Moderate';
  String purpose = 'Holiday';
  final Set<String> interests = {'Culture', 'Food', 'Heritage'};

  final personalities = const [
    (
      'Explorer',
      Icons.explore_rounded,
      'I enjoy discovering new places and flexible experiences.'
    ),
    (
      'Planner',
      Icons.event_note_rounded,
      'I prefer organised schedules and clear plans.'
    ),
    (
      'Social',
      Icons.groups_rounded,
      'I enjoy lively places, events and shared experiences.'
    ),
    (
      'Relaxed',
      Icons.spa_outlined,
      'I prefer slower travel with more rest time.'
    ),
    (
      'Balanced',
      Icons.balance_rounded,
      'I like a mix of planning, exploration and free time.'
    ),
  ];

  final sleepingTypes = const [
    'Early riser',
    'Night owl',
    'Comfort-focused',
    'Flexible',
  ];
  final travelTypes = const [
    'Adventure',
    'Culture',
    'Food',
    'Nature',
    'Leisure',
    'Shopping',
    'Mixed',
  ];
  final budgets = const ['Budget', 'Moderate', 'Premium'];
  final paces = const ['Relaxed', 'Moderate', 'Packed'];
  final purposes = const [
    'Holiday',
    'Family trip',
    'Solo travel',
    'Business trip',
    'Educational trip',
  ];
  final interestOptions = const [
    'Culture',
    'Food',
    'Heritage',
    'Nature',
    'Adventure',
    'Shopping',
    'Photography',
    'Nightlife',
  ];

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    if (widget.loadExisting) {
      Future.microtask(load);
    } else {
      loading = false;
    }
  }

  String normalise(dynamic value, List<String> options, String fallback) {
    final raw = (value ?? '').toString().trim().toLowerCase();
    for (final item in options) {
      if (item.toLowerCase() == raw) return item;
    }
    return fallback;
  }

  Future<void> load() async {
    if (!loading) {
      setState(() {
        loading = true;
        loadError = null;
      });
    }
    try {
      final data = await api.get('/api/fr2/preferences');
      final raw = data['preferences'];
      if (raw is Map) {
        final p = Map<String, dynamic>.from(raw);
        personality = normalise(
          p['travelPersonality'],
          personalities.map((e) => e.$1).toList(),
          personality,
        );
        sleepingType =
            normalise(p['sleepingType'], sleepingTypes, sleepingType);
        travelType = normalise(p['travelType'], travelTypes, travelType);
        budget = normalise(p['budgetRange'], budgets, budget);
        pace = normalise(p['travelPace'], paces, pace);
        purpose = normalise(p['travelPurpose'], purposes, purpose);
        final values = p['interests'] as List? ?? [];
        if (values.isNotEmpty) {
          interests
            ..clear()
            ..addAll(values.map((e) => e.toString()));
        }
      }
    } catch (failure) {
      loadError = userFacingApiError(failure);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> save() async {
    if (interests.isEmpty) {
      _message('Select at least one travel interest.');
      return;
    }
    setState(() => busy = true);
    try {
      await api.put('/api/fr2/preferences', {
        'travelPersonality': personality,
        'sleepingType': sleepingType,
        'travelType': travelType,
        'interests': interests.toList(),
        'budgetRange': budget,
        'travelPace': pace,
        'travelPurpose': purpose,
      });
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Travel preferences saved.')),
      );
      if (widget.onboarding) {
        widget.onCompleted?.call();
      } else {
        Navigator.maybePop(context);
      }
    } catch (failure) {
      _message(
        userFacingApiError(failure),
        retry: isBackendConnectionFailure(failure) ? save : null,
      );
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void _message(String text, {VoidCallback? retry}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(text),
        action: retry == null
            ? null
            : SnackBarAction(label: 'Retry', onPressed: retry),
      ),
    );
  }

  void next() {
    if (page == 3 && interests.isEmpty) {
      _message('Choose at least one interest before continuing.');
      return;
    }
    if (page >= 5) {
      save();
      return;
    }
    controller.nextPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  void previous() {
    if (page == 0) return;
    controller.previousPage(
      duration: const Duration(milliseconds: 260),
      curve: Curves.easeOutCubic,
    );
  }

  Widget optionTile({
    required String title,
    required String selectedValue,
    required ValueChanged<String> onSelected,
    String? subtitle,
    IconData? icon,
  }) {
    final selected = title == selectedValue;
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Material(
        color: selected ? InkWashColors.cream : Colors.white,
        borderRadius: BorderRadius.circular(17),
        child: InkWell(
          borderRadius: BorderRadius.circular(17),
          onTap: () => onSelected(title),
          child: Container(
            padding: const EdgeInsets.all(15),
            decoration: BoxDecoration(
              borderRadius: BorderRadius.circular(17),
              border: Border.all(
                color:
                    selected ? InkWashColors.blueGrey : const Color(0xFFE3E3DE),
                width: selected ? 1.5 : 1,
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                if (icon != null) ...[
                  Container(
                    width: 42,
                    height: 42,
                    decoration: BoxDecoration(
                      color: selected ? Colors.white : InkWashColors.paleBlue,
                      borderRadius: BorderRadius.circular(13),
                    ),
                    child: Icon(icon, color: InkWashColors.blueGrey),
                  ),
                  const SizedBox(width: 11),
                ],
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(title,
                          style: const TextStyle(fontWeight: FontWeight.w800)),
                      if (subtitle != null) ...[
                        const SizedBox(height: 3),
                        Text(
                          subtitle,
                          style: const TextStyle(
                              color: InkWashColors.mutedInk, fontSize: 12),
                        ),
                      ],
                    ],
                  ),
                ),
                Icon(
                  selected
                      ? Icons.check_circle_rounded
                      : Icons.radio_button_unchecked_rounded,
                  color: selected
                      ? InkWashColors.blueGrey
                      : InkWashColors.softGrey,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget pageHeader(String eyebrow, String title, String subtitle) => Padding(
        padding: const EdgeInsets.only(bottom: 18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              eyebrow,
              style: const TextStyle(
                color: InkWashColors.blueGrey,
                fontSize: 12,
                fontWeight: FontWeight.w900,
                letterSpacing: .8,
              ),
            ),
            const SizedBox(height: 5),
            Text(
              title,
              style: const TextStyle(fontSize: 25, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 6),
            Text(subtitle,
                style: const TextStyle(color: InkWashColors.mutedInk)),
          ],
        ),
      );

  @override
  Widget build(BuildContext context) {
    if (loading) {
      return const Scaffold(
        body: AppLoadingState(message: 'Loading your travel profile…'),
      );
    }

    if (loadError != null) {
      return Scaffold(
        body: AppErrorState(
          message: loadError!,
          retryLabel: 'Retry',
          onRetry: load,
        ),
      );
    }

    return PopScope(
      canPop: !widget.onboarding,
      child: Scaffold(
        appBar: AppBar(
          automaticallyImplyLeading: !widget.onboarding,
          title: Text(widget.onboarding
              ? 'Set up your travel profile'
              : 'Travel preferences'),
          actions: [
            if (widget.onboarding)
              TextButton(
                onPressed: busy ? null : () => AuthService().logout(),
                child: const Text('Sign out'),
              ),
          ],
        ),
        body: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(18, 4, 18, 8),
              child: Row(
                children: List.generate(6, (i) {
                  return Expanded(
                    child: Container(
                      height: 5,
                      margin: EdgeInsets.only(right: i == 5 ? 0 : 5),
                      decoration: BoxDecoration(
                        color: i <= page
                            ? InkWashColors.blueGrey
                            : InkWashColors.softGrey.withValues(alpha: .45),
                        borderRadius: BorderRadius.circular(10),
                      ),
                    ),
                  );
                }),
              ),
            ),
            Expanded(
              child: PageView(
                controller: controller,
                physics: const NeverScrollableScrollPhysics(),
                onPageChanged: (value) => setState(() => page = value),
                children: [
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader('1 OF 6', 'What kind of traveller are you?',
                          'Choose the description that best matches how you usually approach a trip.'),
                      ...personalities.map((item) => optionTile(
                            title: item.$1,
                            subtitle: item.$3,
                            icon: item.$2,
                            selectedValue: personality,
                            onSelected: (value) =>
                                setState(() => personality = value),
                          )),
                    ],
                  ),
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader(
                          '2 OF 6',
                          'When does your travel day work best?',
                          'This helps TravelMate place activities at more suitable times.'),
                      ...sleepingTypes.map((item) => optionTile(
                            title: item,
                            selectedValue: sleepingType,
                            onSelected: (value) =>
                                setState(() => sleepingType = value),
                            icon: item == 'Early riser'
                                ? Icons.wb_sunny_outlined
                                : item == 'Night owl'
                                    ? Icons.nightlight_outlined
                                    : Icons.bedtime_outlined,
                          )),
                    ],
                  ),
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader('3 OF 6', 'What travel style do you prefer?',
                          'TravelMate uses this with your interests to shape suggestions for you.'),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: travelTypes
                            .map((item) => ChoiceChip(
                                  selected: travelType == item,
                                  label: Text(item),
                                  onSelected: (_) =>
                                      setState(() => travelType = item),
                                ))
                            .toList(),
                      ),
                    ],
                  ),
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader('4 OF 6', 'What are you interested in?',
                          'Choose all that apply so your suggestions reflect what you enjoy.'),
                      Wrap(
                        spacing: 8,
                        runSpacing: 8,
                        children: interestOptions
                            .map((item) => FilterChip(
                                  selected: interests.contains(item),
                                  label: Text(item),
                                  onSelected: (selected) => setState(() {
                                    if (selected) {
                                      interests.add(item);
                                    } else {
                                      interests.remove(item);
                                    }
                                  }),
                                ))
                            .toList(),
                      ),
                    ],
                  ),
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader('5 OF 6', 'Choose your budget and travel pace',
                          'These settings shape suggested places and how full each day feels.'),
                      const Text('Budget preference',
                          style: TextStyle(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 8),
                      ...budgets.map((item) => optionTile(
                            title: item,
                            selectedValue: budget,
                            onSelected: (value) =>
                                setState(() => budget = value),
                            icon: Icons.account_balance_wallet_outlined,
                          )),
                      const SizedBox(height: 9),
                      const Text('Travel pace',
                          style: TextStyle(fontWeight: FontWeight.w900)),
                      const SizedBox(height: 8),
                      Wrap(
                        spacing: 8,
                        children: paces
                            .map((item) => ChoiceChip(
                                  selected: pace == item,
                                  label: Text(item),
                                  onSelected: (_) =>
                                      setState(() => pace = item),
                                ))
                            .toList(),
                      ),
                    ],
                  ),
                  ListView(
                    padding: const EdgeInsets.fromLTRB(18, 16, 18, 22),
                    children: [
                      pageHeader(
                          '6 OF 6',
                          'What is the main purpose of this travel profile?',
                          'You can update all questionnaire answers later from Profile.'),
                      ...purposes.map((item) => optionTile(
                            title: item,
                            selectedValue: purpose,
                            onSelected: (value) =>
                                setState(() => purpose = value),
                            icon: Icons.flag_outlined,
                          )),
                      const SizedBox(height: 12),
                      InkCard(
                        color: InkWashColors.cream,
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const Text('Your TravelMate profile',
                                style: TextStyle(fontWeight: FontWeight.w900)),
                            const SizedBox(height: 7),
                            Text(
                                '$personality • $travelType • $budget • $pace'),
                            const SizedBox(height: 3),
                            Text(interests.join(', ')),
                          ],
                        ),
                      ),
                    ],
                  ),
                ],
              ),
            ),
            SafeArea(
              top: false,
              child: Container(
                padding: const EdgeInsets.fromLTRB(18, 10, 18, 12),
                decoration: const BoxDecoration(
                  color: Colors.white,
                  border: Border(top: BorderSide(color: Color(0xFFE7E7E2))),
                ),
                child: Row(
                  children: [
                    if (page > 0)
                      Expanded(
                        child: OutlinedButton(
                          onPressed: busy ? null : previous,
                          child: const Text('Back'),
                        ),
                      ),
                    if (page > 0) const SizedBox(width: 9),
                    Expanded(
                      flex: page > 0 ? 1 : 2,
                      child: FilledButton(
                        onPressed: busy ? null : next,
                        child: Text(
                          busy
                              ? 'Saving...'
                              : page == 5
                                  ? (widget.onboarding
                                      ? 'Start using TravelMate'
                                      : 'Save changes')
                                  : 'Continue',
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
