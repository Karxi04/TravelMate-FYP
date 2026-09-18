import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class EditProfileScreen extends StatefulWidget {
  const EditProfileScreen({super.key});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  final api = ApiService();
  final formKey = GlobalKey<FormState>();

  final name = TextEditingController();
  final phone = TextEditingController();
  final dob = TextEditingController();
  final nationality = TextEditingController();
  final currentCity = TextEditingController();
  final emergencyName = TextEditingController();
  final emergencyPhone = TextEditingController();
  final travelBio = TextEditingController();

  String language = 'English';
  String gender = 'Prefer not to say';
  String emergencyRelationship = 'Family';
  bool loading = true;
  bool saving = false;

  final languages = const ['English', 'Bahasa Malaysia', '中文', 'Tamil'];
  final genders = const ['Prefer not to say', 'Female', 'Male', 'Other'];
  final relationships = const ['Family', 'Parent', 'Sibling', 'Partner', 'Friend', 'Other'];

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr1/me');
      final p = data['profile'] is Map ? Map<String, dynamic>.from(data['profile'] as Map) : <String, dynamic>{};
      name.text = (p['name'] ?? '').toString();
      phone.text = (p['phoneNo'] ?? '').toString();
      dob.text = (p['dateOfBirth'] ?? '').toString();
      nationality.text = (p['nationality'] ?? '').toString();
      currentCity.text = (p['currentCity'] ?? '').toString();
      emergencyName.text = (p['emergencyContactName'] ?? '').toString();
      emergencyPhone.text = (p['emergencyContact'] ?? '').toString();
      travelBio.text = (p['travelBio'] ?? '').toString();
      final savedLanguage = (p['preferredLanguage'] ?? 'English').toString();
      final savedGender = (p['gender'] ?? 'Prefer not to say').toString();
      final savedRelationship = (p['emergencyRelationship'] ?? 'Family').toString();
      language = languages.contains(savedLanguage) ? savedLanguage : 'English';
      gender = genders.contains(savedGender) ? savedGender : 'Prefer not to say';
      emergencyRelationship = relationships.contains(savedRelationship) ? savedRelationship : 'Family';
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> pickBirthDate() async {
    final initial = DateTime.tryParse(dob.text) ?? DateTime(2000, 1, 1);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial,
      firstDate: DateTime(1920, 1, 1),
      lastDate: DateTime.now(),
    );
    if (picked != null) {
      dob.text = '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    }
  }

  Future<void> save() async {
    if (!(formKey.currentState?.validate() ?? false)) return;
    setState(() => saving = true);
    try {
      await api.put('/api/fr1/me', {
        'name': name.text.trim(),
        'phoneNo': phone.text.trim(),
        'dateOfBirth': dob.text.trim(),
        'nationality': nationality.text.trim(),
        'preferredLanguage': language,
        'gender': gender,
        'currentCity': currentCity.text.trim(),
        'emergencyContactName': emergencyName.text.trim(),
        'emergencyContact': emergencyPhone.text.trim(),
        'emergencyRelationship': emergencyRelationship,
        'travelBio': travelBio.text.trim(),
      });
      await FirebaseAuth.instance.currentUser?.updateDisplayName(name.text.trim());
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(const SnackBar(content: Text('Profile updated.')));
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) showError(context, e);
    } finally {
      if (mounted) setState(() => saving = false);
    }
  }

  Widget field({
    required TextEditingController controller,
    required String label,
    required IconData icon,
    TextInputType? keyboardType,
    String? hint,
    String? Function(String?)? validator,
    int maxLines = 1,
    bool readOnly = false,
    VoidCallback? onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 10),
      child: TextFormField(
        controller: controller,
        keyboardType: keyboardType,
        maxLines: maxLines,
        readOnly: readOnly,
        onTap: onTap,
        validator: validator,
        decoration: InputDecoration(labelText: label, hintText: hint, prefixIcon: Icon(icon)),
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
    final user = FirebaseAuth.instance.currentUser;
    return Scaffold(
      appBar: AppBar(title: const Text('Edit profile')),
      body: loading
          ? const Center(child: CircularProgressIndicator())
          : Form(
              key: formKey,
              child: ListView(
                padding: const EdgeInsets.fromLTRB(18, 8, 18, 30),
                children: [
                  InkCard(
                    color: InkWashColors.cream,
                    child: Row(
                      children: [
                        CircleAvatar(
                          radius: 31,
                          backgroundColor: InkWashColors.blueGrey,
                          child: Text(name.text.trim().isEmpty ? 'T' : name.text.trim()[0].toUpperCase(), style: const TextStyle(color: Colors.white, fontSize: 22, fontWeight: FontWeight.w900)),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text('Traveller account', style: TextStyle(fontWeight: FontWeight.w900, fontSize: 18)),
                              const SizedBox(height: 3),
                              Text(user?.email ?? '', style: const TextStyle(color: InkWashColors.mutedInk)),
                              const SizedBox(height: 6),
                              const Text('Email is managed by your sign-in account.', style: TextStyle(fontSize: 12, color: InkWashColors.mutedInk)),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(title: 'Basic information', subtitle: 'Information used for your account and trip experience'),
                  const SizedBox(height: 10),
                  field(
                    controller: name,
                    label: 'Full name',
                    icon: Icons.person_outline_rounded,
                    validator: (v) => (v ?? '').trim().length < 2 ? 'Enter your full name.' : null,
                  ),
                  field(
                    controller: phone,
                    label: 'Phone number',
                    icon: Icons.phone_outlined,
                    keyboardType: TextInputType.phone,
                    hint: '+60 12-345 6789',
                  ),
                  field(
                    controller: dob,
                    label: 'Date of birth',
                    icon: Icons.cake_outlined,
                    readOnly: true,
                    onTap: pickBirthDate,
                  ),
                  field(controller: nationality, label: 'Nationality', icon: Icons.public_rounded),
                  field(controller: currentCity, label: 'Current city', icon: Icons.location_city_outlined, hint: 'e.g. Kuala Lumpur'),
                  const SizedBox(height: 2),
                  DropdownButtonFormField<String>(
                    initialValue: gender,
                    items: genders.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                    onChanged: (v) => setState(() => gender = v ?? gender),
                    decoration: const InputDecoration(labelText: 'Gender', prefixIcon: Icon(Icons.badge_outlined)),
                  ),
                  const SizedBox(height: 10),
                  DropdownButtonFormField<String>(
                    initialValue: language,
                    items: languages.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                    onChanged: (v) => setState(() => language = v ?? language),
                    decoration: const InputDecoration(labelText: 'Preferred language', prefixIcon: Icon(Icons.language_rounded)),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(title: 'Emergency contact', subtitle: 'Optional contact information for your own trip record'),
                  const SizedBox(height: 10),
                  field(controller: emergencyName, label: 'Contact name', icon: Icons.person_pin_outlined),
                  field(controller: emergencyPhone, label: 'Contact phone', icon: Icons.emergency_outlined, keyboardType: TextInputType.phone),
                  DropdownButtonFormField<String>(
                    initialValue: emergencyRelationship,
                    items: relationships.map((e) => DropdownMenuItem(value: e, child: Text(e))).toList(),
                    onChanged: (v) => setState(() => emergencyRelationship = v ?? emergencyRelationship),
                    decoration: const InputDecoration(labelText: 'Relationship', prefixIcon: Icon(Icons.group_outlined)),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(title: 'About your travel style', subtitle: 'A short profile note separate from the questionnaire'),
                  const SizedBox(height: 10),
                  field(
                    controller: travelBio,
                    label: 'Travel bio',
                    icon: Icons.edit_note_rounded,
                    maxLines: 4,
                    hint: 'e.g. I enjoy local food, museums and relaxed walking days.',
                  ),
                  const SizedBox(height: 10),
                  SizedBox(
                    height: 52,
                    child: FilledButton.icon(
                      onPressed: saving ? null : save,
                      icon: const Icon(Icons.save_outlined),
                      label: Text(saving ? 'Saving...' : 'Save changes'),
                    ),
                  ),
                ],
              ),
            ),
    );
  }
}
