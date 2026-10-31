import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import '../fr02_travel_preference/preferences_screen.dart';
import 'edit_profile_screen.dart';
import '../fr03_destination_search_information/favourites_screen.dart';
import '../fr09_payment/payment_history_screen.dart';
import '../fr10_feedback_rating/feedback_screen.dart';

class ProfileTab extends StatefulWidget {
  final ApiService? api;
  final Future<void> Function()? onSignOut;

  const ProfileTab({super.key, this.api, this.onSignOut});

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  late final ApiService api;
  final name = TextEditingController();
  final phone = TextEditingController();
  final language = TextEditingController(text: 'English');

  Map<String, dynamic>? profile;
  Map<String, dynamic> preferences = {};
  Map<String, dynamic> preferenceLearning = {};
  bool loading = true;
  bool resettingLearning = false;
  String? loadError;

  Future<void> load() async {
    if (mounted) {
      setState(() {
        loading = true;
        loadError = null;
      });
    }
    try {
      final data = await api.get('/api/fr1/me');
      final raw = data['profile'];
      if (raw is! Map) return;

      final p = Map<String, dynamic>.from(raw);
      profile = p;
      name.text = p['name'] ?? '';
      phone.text = p['phoneNo'] ?? '';
      language.text = p['preferredLanguage'] ?? 'English';
      try {
        final preferenceData = await api.get('/api/fr2/preferences');
        final rawPreferences = preferenceData['preferences'];
        if (rawPreferences is Map) {
          preferences = Map<String, dynamic>.from(rawPreferences);
        }
      } catch (_) {
        preferences = {};
      }
      try {
        final learningData = await api.get('/api/fr4/preference-feedback');
        final rawLearning = learningData['learning'];
        preferenceLearning =
            rawLearning is Map ? Map<String, dynamic>.from(rawLearning) : {};
      } catch (_) {
        preferenceLearning = {};
      }
    } catch (_) {
      loadError = 'We couldn’t load your profile. Try again.';
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> editPreferences() async {
    await Navigator.push(
      context,
      MaterialPageRoute(builder: (_) => PreferencesScreen(api: api)),
    );
    await load();
  }

  Future<void> resetLearnedPreferences() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.restart_alt_rounded),
        title: const Text('Reset learned preferences?'),
        content: const Text(
          'This clears what TravelMate learned from “More like this” and “Not for me”. Your saved travel preferences, trips and reviews will stay unchanged.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Keep learning'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Reset learning'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    setState(() => resettingLearning = true);
    try {
      final data = await api.delete('/api/fr4/preference-feedback');
      if (data is Map && data['ok'] == false) {
        throw Exception(
            data['error'] ?? 'Learned preferences could not reset.');
      }
      if (!mounted) return;
      setState(() {
        preferenceLearning = data is Map && data['learning'] is Map
            ? Map<String, dynamic>.from(data['learning'] as Map)
            : {};
      });
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Learned preferences were reset.')),
      );
    } catch (error) {
      if (mounted) showError(context, error);
    } finally {
      if (mounted) setState(() => resettingLearning = false);
    }
  }

  Future<void> signOut() async {
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        icon: const Icon(Icons.logout_rounded),
        title: const Text('Sign out of TravelMate?'),
        content: const Text(
          'Your saved trips will remain available when you sign in again.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('Stay signed in'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('Sign out'),
          ),
        ],
      ),
    );
    if (confirmed != true) return;
    await (widget.onSignOut?.call() ?? AuthService().logout());
  }

  Future<void> editProfile() async {
    final updated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => EditProfileScreen(api: api)),
    );
    if (updated == true) await load();
  }

  void open(Widget screen) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
  }

  String accountEmail() {
    final saved = (profile?['email'] ?? '').toString().trim();
    if (saved.isNotEmpty) return saved;
    try {
      return FirebaseAuth.instance.currentUser?.email ?? '';
    } catch (_) {
      return '';
    }
  }

  Widget menuTile(
    IconData icon,
    String title,
    String subtitle,
    VoidCallback onTap, {
    bool danger = false,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Material(
        color: Colors.white,
        borderRadius: BorderRadius.circular(17),
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(17),
          child: Container(
            padding: const EdgeInsets.all(13),
            decoration: BoxDecoration(
              border: Border.all(color: const Color(0xFFE3E3DE)),
              borderRadius: BorderRadius.circular(17),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  backgroundColor:
                      danger ? const Color(0xFFFFEEEE) : InkWashColors.paleBlue,
                  child: Icon(
                    icon,
                    color:
                        danger ? Colors.red.shade700 : InkWashColors.blueGrey,
                  ),
                ),
                const SizedBox(width: 11),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        title,
                        style: TextStyle(
                          fontWeight: FontWeight.w800,
                          color:
                              danger ? Colors.red.shade800 : InkWashColors.ink,
                        ),
                      ),
                      Text(
                        subtitle,
                        style: const TextStyle(
                          color: InkWashColors.mutedInk,
                          fontSize: 12,
                        ),
                      ),
                    ],
                  ),
                ),
                const Icon(
                  Icons.chevron_right_rounded,
                  color: InkWashColors.softGrey,
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }

  @override
  void initState() {
    super.initState();
    api = widget.api ?? ApiService();
    Future.microtask(load);
  }

  @override
  Widget build(BuildContext context) {
    final displayName = (profile?['name'] ?? 'Traveller').toString();
    final email = accountEmail();
    final personality =
        (preferences['travelPersonality'] ?? 'Discover your travel style')
            .toString();
    final interests = (preferences['interests'] as List? ?? [])
        .map((item) => item.toString())
        .where((item) => item.trim().isNotEmpty)
        .take(3)
        .toList();
    final pace = (preferences['travelPace'] ?? '').toString().trim();
    final styleDetails = <String>[
      ...interests,
      if (pace.isNotEmpty) '$pace pace',
    ];
    final tendencies = (preferenceLearning['tendencies'] as List? ?? const [])
        .whereType<Map>()
        .map((item) => Map<String, dynamic>.from(item))
        .toList();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Profile'),
        actions: [
          IconButton(
            onPressed: editProfile,
            icon: const Icon(Icons.edit_outlined),
            tooltip: 'Edit account details',
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 30),
          children: [
            if (loading)
              const AppLoadingState(message: 'Loading your travel profile…')
            else if (loadError != null)
              AppErrorState(message: loadError!, onRetry: load)
            else ...[
              InkCard(
                color: InkWashColors.cream,
                child: Row(
                  children: [
                    CircleAvatar(
                      radius: 33,
                      backgroundColor: InkWashColors.blueGrey,
                      child: Text(
                        displayName.isEmpty
                            ? 'T'
                            : displayName[0].toUpperCase(),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 24,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    const SizedBox(width: 13),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            displayName,
                            style: const TextStyle(
                              fontSize: 21,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                          Text(
                            email,
                            style:
                                const TextStyle(color: InkWashColors.mutedInk),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              const TravelSectionHeader(
                title: 'Travel style',
                subtitle: 'Used to make your suggestions feel more relevant',
              ),
              const SizedBox(height: 10),
              InkCard(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        const CircleAvatar(
                          backgroundColor: InkWashColors.paleBlue,
                          child: Icon(Icons.explore_outlined,
                              color: InkWashColors.blueGrey),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            personality,
                            style: Theme.of(context).textTheme.titleLarge,
                          ),
                        ),
                      ],
                    ),
                    if (styleDetails.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Text(
                        styleDetails.join(' · '),
                        style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                              color: AppColors.textSecondary,
                            ),
                      ),
                    ],
                    const SizedBox(height: 10),
                    Text(
                      'TravelMate adapts recommendations using your feedback.',
                      style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                            color: AppColors.textSecondary,
                          ),
                    ),
                    if (tendencies.isNotEmpty) ...[
                      const SizedBox(height: 10),
                      Wrap(
                        spacing: AppSpacing.xs,
                        runSpacing: AppSpacing.xs,
                        children: tendencies.map((item) {
                          final up = item['direction'] == 'up';
                          return StatusChip(
                            text:
                                '${up ? 'More' : 'Less'} ${(item['label'] ?? item['concept'] ?? 'similar places')}',
                            icon: up
                                ? Icons.trending_up_rounded
                                : Icons.trending_down_rounded,
                            tone: AppStatusTone.neutral,
                          );
                        }).toList(),
                      ),
                    ],
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: AppSpacing.xs,
                      runSpacing: AppSpacing.xs,
                      children: [
                        OutlinedButton.icon(
                          onPressed: editPreferences,
                          icon: const Icon(Icons.tune_rounded),
                          label: const Text('Edit travel preferences'),
                        ),
                        if (preferenceLearning['hasLearnedPreferences'] == true)
                          TextButton.icon(
                            key: const ValueKey('reset-learned-preferences'),
                            onPressed: resettingLearning
                                ? null
                                : resetLearnedPreferences,
                            icon: resettingLearning
                                ? const SizedBox.square(
                                    dimension: 16,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                    ),
                                  )
                                : const Icon(Icons.restart_alt_rounded),
                            label: const Text('Reset learned preferences'),
                          ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              const TravelSectionHeader(title: 'Account'),
              const SizedBox(height: 10),
              InkCard(
                child: Column(
                  children: [
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.person_outline_rounded),
                      title: const Text('Name'),
                      subtitle: Text(displayName),
                    ),
                    ListTile(
                      contentPadding: EdgeInsets.zero,
                      leading: const Icon(Icons.email_outlined),
                      title: const Text('Email'),
                      subtitle: Text(email),
                    ),
                    Align(
                      alignment: Alignment.centerLeft,
                      child: TextButton.icon(
                        onPressed: editProfile,
                        icon: const Icon(Icons.edit_outlined),
                        label: const Text('Edit account details'),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 22),
              const TravelSectionHeader(
                title: 'Saved and travel activity',
              ),
              const SizedBox(height: 10),
              menuTile(
                Icons.favorite_border_rounded,
                'Favourite destinations',
                'Places saved from Explore',
                () => open(const FavouritesScreen()),
              ),
              menuTile(
                Icons.star_outline_rounded,
                'My feedback',
                'View, edit or delete your feedback',
                () => open(const FeedbackScreen()),
              ),
              menuTile(
                Icons.receipt_long_outlined,
                'Travel Records',
                'Saved travel options and historical records',
                () => open(TravelRecordsScreen(api: api)),
              ),
              const SizedBox(height: 18),
              const TravelSectionHeader(title: 'Settings'),
              const SizedBox(height: 8),
              menuTile(
                Icons.logout_rounded,
                'Sign out',
                'Sign out from this device',
                signOut,
                danger: true,
              ),
            ],
          ],
        ),
      ),
    );
  }
}
