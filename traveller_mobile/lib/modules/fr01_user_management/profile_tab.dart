import 'package:flutter/material.dart';
import 'package:firebase_auth/firebase_auth.dart';
import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import '../../theme/app_theme.dart';
import '../fr02_travel_preference/preferences_screen.dart';
import 'profile_details_screen.dart';
import 'edit_profile_screen.dart';
import '../fr03_destination_search_information/favourites_screen.dart';
import '../fr09_payment/payment_screen.dart';
import '../fr10_feedback_rating/feedback_screen.dart';

class ProfileTab extends StatefulWidget {
  const ProfileTab({super.key});

  @override
  State<ProfileTab> createState() => _ProfileTabState();
}

class _ProfileTabState extends State<ProfileTab> {
  final api = ApiService();
  final name = TextEditingController();
  final phone = TextEditingController();
  final language = TextEditingController(text: 'English');

  Map<String, dynamic>? profile;

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr1/me');
      final raw = data['profile'];
      if (raw is! Map) return;

      final p = Map<String, dynamic>.from(raw);
      profile = p;
      name.text = p['name'] ?? '';
      phone.text = p['phoneNo'] ?? '';
      language.text = p['preferredLanguage'] ?? 'English';

      if (mounted) setState(() {});
    } catch (e) {
      if (mounted) showError(context, e);
    }
  }

  Future<void> editProfile() async {
    final updated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const EditProfileScreen()),
    );
    if (updated == true) await load();
  }

  void open(Widget screen) {
    Navigator.push(context, MaterialPageRoute(builder: (_) => screen));
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
                    color: danger ? Colors.red.shade700 : InkWashColors.blueGrey,
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
                          color: danger ? Colors.red.shade800 : InkWashColors.ink,
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
    Future.microtask(load);
  }

  @override
  Widget build(BuildContext context) {
    final displayName = (profile?['name'] ?? 'Traveller').toString();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Profile'),
        actions: [
          IconButton(
            onPressed: editProfile,
            icon: const Icon(Icons.edit_outlined),
          ),
        ],
      ),
      body: RefreshIndicator(
        onRefresh: load,
        child: ListView(
          padding: const EdgeInsets.fromLTRB(18, 8, 18, 30),
          children: [
            InkWell(
              borderRadius: BorderRadius.circular(20),
              onTap: () => open(const ProfileDetailsScreen()),
              child: InkCard(
              color: InkWashColors.cream,
              child: Row(
                children: [
                  CircleAvatar(
                    radius: 33,
                    backgroundColor: InkWashColors.blueGrey,
                    child: Text(
                      displayName.isEmpty ? 'T' : displayName[0].toUpperCase(),
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
                          FirebaseAuth.instance.currentUser?.email ?? '',
                          style: const TextStyle(color: InkWashColors.mutedInk),
                        ),
                        const SizedBox(height: 7),
                        TravelStatusPill(
                          text: (profile?['role'] ?? 'traveller').toString(),
                          icon: Icons.verified_user_outlined,
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
            ),
            const SizedBox(height: 22),
            const TravelSectionHeader(
              title: 'Your travel profile',
              subtitle: 'Personalisation, saved places and contributions',
            ),
            const SizedBox(height: 10),
            menuTile(
              Icons.person_outline_rounded,
              'Personal details',
              'Email, phone, nationality, language and account information',
              () => open(const ProfileDetailsScreen()),
            ),
            menuTile(
              Icons.tune_rounded,
              'Travel preferences',
              'Personality, interests, budget and pace',
              () => open(const PreferencesScreen()),
            ),
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
              'Payment records',
              'Card payments and transaction records',
              () => open(const PaymentScreen()),
            ),
            const SizedBox(height: 18),
            const TravelSectionHeader(title: 'Account'),
            const SizedBox(height: 8),
            menuTile(
              Icons.edit_outlined,
              'Edit profile',
              'Personal, contact, emergency and travel profile information',
              editProfile,
            ),
            menuTile(
              Icons.logout_rounded,
              'Log out',
              'Sign out from this device',
              () => AuthService().logout(),
              danger: true,
            ),
          ],
        ),
      ),
    );
  }
}
