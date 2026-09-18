import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'edit_profile_screen.dart';

class ProfileDetailsScreen extends StatefulWidget {
  const ProfileDetailsScreen({super.key});

  @override
  State<ProfileDetailsScreen> createState() => _ProfileDetailsScreenState();
}

class _ProfileDetailsScreenState extends State<ProfileDetailsScreen> {
  final api = ApiService();
  Map<String, dynamic>? profile;
  bool loading = true;

  Future<void> load() async {
    setState(() => loading = true);
    try {
      final data = await api.get('/api/fr1/me');
      final raw = data['profile'];
      if (raw is Map && mounted) {
        setState(() => profile = Map<String, dynamic>.from(raw));
      }
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> edit() async {
    final updated = await Navigator.push<bool>(
      context,
      MaterialPageRoute(builder: (_) => const EditProfileScreen()),
    );
    if (updated == true) await load();
  }

  Widget infoTile(IconData icon, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: InkCard(
        child: Row(
          children: [
            Container(
              width: 44,
              height: 44,
              decoration: BoxDecoration(color: InkWashColors.paleBlue, borderRadius: BorderRadius.circular(14)),
              child: Icon(icon, color: InkWashColors.blueGrey),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(label, style: const TextStyle(color: InkWashColors.mutedInk, fontSize: 12)),
                  const SizedBox(height: 2),
                  Text(value.trim().isEmpty ? 'Not provided' : value, style: const TextStyle(fontWeight: FontWeight.w800)),
                ],
              ),
            ),
          ],
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
    final p = profile ?? <String, dynamic>{};
    final firebaseUser = FirebaseAuth.instance.currentUser;
    final name = (p['name'] ?? 'Traveller').toString();

    return Scaffold(
      appBar: AppBar(
        title: const Text('Personal details'),
        actions: [IconButton(onPressed: loading ? null : edit, icon: const Icon(Icons.edit_outlined))],
      ),
      body: loading && profile == null
          ? const Center(child: CircularProgressIndicator())
          : RefreshIndicator(
              onRefresh: load,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 28),
                children: [
                  InkCard(
                    color: InkWashColors.cream,
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 32,
                          backgroundColor: InkWashColors.blueGrey,
                          child: Text(name.isEmpty ? 'T' : name[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 23, fontWeight: FontWeight.w900)),
                        ),
                        const SizedBox(width: 13),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(name, style: const TextStyle(fontSize: 21, fontWeight: FontWeight.w900)),
                              const SizedBox(height: 3),
                              Text((firebaseUser?.email ?? p['email'] ?? '').toString(), style: const TextStyle(color: InkWashColors.mutedInk)),
                              const SizedBox(height: 7),
                              TravelStatusPill(text: (p['status'] ?? 'active').toString(), icon: Icons.verified_user_outlined),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(title: 'Contact & identity', subtitle: 'Details used to personalise and manage your TravelMate account'),
                  const SizedBox(height: 10),
                  infoTile(Icons.email_outlined, 'Email address', (firebaseUser?.email ?? p['email'] ?? '').toString()),
                  infoTile(Icons.phone_outlined, 'Phone number', (p['phoneNo'] ?? '').toString()),
                  infoTile(Icons.cake_outlined, 'Date of birth', (p['dateOfBirth'] ?? '').toString()),
                  infoTile(Icons.public_rounded, 'Nationality', (p['nationality'] ?? '').toString()),
                  infoTile(Icons.location_city_outlined, 'Current city', (p['currentCity'] ?? '').toString()),
                  infoTile(Icons.badge_outlined, 'Gender', (p['gender'] ?? 'Prefer not to say').toString()),
                  infoTile(Icons.language_rounded, 'Preferred language', (p['preferredLanguage'] ?? 'English').toString()),
                  infoTile(Icons.person_pin_outlined, 'Emergency contact name', (p['emergencyContactName'] ?? '').toString()),
                  infoTile(Icons.emergency_outlined, 'Emergency contact phone', (p['emergencyContact'] ?? '').toString()),
                  infoTile(Icons.group_outlined, 'Emergency relationship', (p['emergencyRelationship'] ?? '').toString()),
                  infoTile(Icons.edit_note_rounded, 'Travel bio', (p['travelBio'] ?? '').toString()),
                  const SizedBox(height: 14),
                  const TravelSectionHeader(title: 'Account information'),
                  const SizedBox(height: 10),
                  infoTile(Icons.badge_outlined, 'Account role', (p['role'] ?? 'traveller').toString()),
                  infoTile(Icons.shield_outlined, 'Account status', (p['status'] ?? 'active').toString()),
                  infoTile(Icons.calendar_today_outlined, 'Member since', (p['createdAt'] ?? '').toString().split('T').first),
                  const SizedBox(height: 10),
                  FilledButton.icon(onPressed: edit, icon: const Icon(Icons.edit_outlined), label: const Text('Edit personal details')),
                ],
              ),
            ),
    );
  }
}
