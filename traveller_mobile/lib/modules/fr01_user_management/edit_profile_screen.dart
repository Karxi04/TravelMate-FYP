import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../../core/utils/country_city_data.dart';
import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';

class EditProfileScreen extends StatefulWidget {
  final ApiService? api;

  const EditProfileScreen({super.key, this.api});

  @override
  State<EditProfileScreen> createState() => _EditProfileScreenState();
}

class _EditProfileScreenState extends State<EditProfileScreen> {
  late final ApiService api = widget.api ?? ApiService();
  final formKey = GlobalKey<FormState>();

  final name = TextEditingController();
  final phone = TextEditingController();
  final dob = TextEditingController();
  final nationality = TextEditingController();
  final currentCity = TextEditingController();
  final emergencyName = TextEditingController();
  final emergencyPhone = TextEditingController();
  final travelBio = TextEditingController();

  String savedLanguage = 'English';
  String gender = 'Prefer not to say';
  String emergencyRelationship = 'Family';
  bool loading = true;
  bool saving = false;

  final genders = const ['Prefer not to say', 'Female', 'Male', 'Other'];
  final relationships = const [
    'Family',
    'Parent',
    'Sibling',
    'Partner',
    'Friend',
    'Other'
  ];

  @override
  void dispose() {
    name.dispose();
    phone.dispose();
    dob.dispose();
    nationality.dispose();
    currentCity.dispose();
    emergencyName.dispose();
    emergencyPhone.dispose();
    travelBio.dispose();
    super.dispose();
  }

  Future<void> load() async {
    try {
      final data = await api.get('/api/fr1/me');
      final p = data['profile'] is Map
          ? Map<String, dynamic>.from(data['profile'] as Map)
          : <String, dynamic>{};
      name.text = (p['name'] ?? '').toString();
      phone.text = (p['phoneNo'] ?? '').toString();
      dob.text = (p['dateOfBirth'] ?? '').toString();
      nationality.text = (p['nationality'] ?? '').toString();
      currentCity.text = (p['currentCity'] ?? '').toString();
      emergencyName.text = (p['emergencyContactName'] ?? '').toString();
      emergencyPhone.text = (p['emergencyContact'] ?? '').toString();
      travelBio.text = (p['travelBio'] ?? '').toString();
      savedLanguage = (p['preferredLanguage'] ?? 'English').toString();
      final currentGender = (p['gender'] ?? 'Prefer not to say').toString();
      final currentRel =
          (p['emergencyRelationship'] ?? 'Family').toString();
      gender =
          genders.contains(currentGender) ? currentGender : 'Prefer not to say';
      emergencyRelationship =
          relationships.contains(currentRel) ? currentRel : 'Family';
    } catch (e) {
      if (mounted) showError(context, AuthService.formatAuthError(e));
    } finally {
      if (mounted) setState(() => loading = false);
    }
  }

  Future<void> pickBirthDate() async {
    final initial = DateTime.tryParse(dob.text) ?? DateTime(2000, 1, 1);
    final now = DateTime.now();
    final today = DateTime(now.year, now.month, now.day);
    final picked = await showDatePicker(
      context: context,
      initialDate: initial.isAfter(today) ? today : initial,
      firstDate: DateTime(1900, 1, 1),
      lastDate: today,
    );
    if (picked != null) {
      dob.text =
          '${picked.year.toString().padLeft(4, '0')}-${picked.month.toString().padLeft(2, '0')}-${picked.day.toString().padLeft(2, '0')}';
    }
  }

  Future<void> pickNationality() async {
    final selected = await _showSearchablePicker(
      context: context,
      title: 'Select nationality / country',
      items: CountryCityData.countries,
      currentValue: nationality.text,
      allowCustom: true,
      customHint: 'Type your country name...',
    );
    if (selected != null && mounted) {
      setState(() => nationality.text = selected);
    }
  }

  Future<void> pickCurrentCity() async {
    final selected = await _showSearchablePicker(
      context: context,
      title: 'Select current city',
      items: CountryCityData.suggestedCities,
      currentValue: currentCity.text,
      allowCustom: true,
      customHint: 'Type your city name...',
    );
    if (selected != null && mounted) {
      setState(() => currentCity.text = selected);
    }
  }

  User? get _currentUser {
    try {
      return FirebaseAuth.instance.currentUser;
    } catch (_) {
      return null;
    }
  }

  Future<void> save() async {
    if (!(formKey.currentState?.validate() ?? false)) return;
    setState(() => saving = true);
    try {
      final payload = <String, dynamic>{
        'name': name.text.trim(),
        'phoneNo': phone.text.trim(),
        'dateOfBirth': dob.text.trim(),
        'nationality': nationality.text.trim(),
        'gender': gender,
        'currentCity': currentCity.text.trim(),
        'emergencyContactName': emergencyName.text.trim(),
        'emergencyContact': emergencyPhone.text.trim(),
        'emergencyRelationship': emergencyRelationship,
        'travelBio': travelBio.text.trim(),
        if (savedLanguage.isNotEmpty) 'preferredLanguage': savedLanguage,
      };

      await api.put('/api/fr1/me', payload);
      try {
        await _currentUser?.updateDisplayName(name.text.trim());
      } catch (_) {}

      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Profile updated.')),
      );
      Navigator.pop(context, true);
    } catch (e) {
      if (mounted) showError(context, AuthService.formatAuthError(e));
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
    Widget? suffix,
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
        decoration: InputDecoration(
          labelText: label,
          hintText: hint,
          prefixIcon: Icon(icon),
          suffixIcon: suffix,
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
    final user = _currentUser;
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
                          child: Text(
                            name.text.trim().isEmpty
                                ? 'T'
                                : name.text.trim()[0].toUpperCase(),
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 22,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              const Text(
                                'Traveller account',
                                style: TextStyle(
                                  fontWeight: FontWeight.w900,
                                  fontSize: 18,
                                ),
                              ),
                              const SizedBox(height: 3),
                              Text(
                                user?.email ?? '',
                                style: const TextStyle(
                                  color: InkWashColors.mutedInk,
                                ),
                              ),
                              const SizedBox(height: 6),
                              const Text(
                                'Email is managed by your sign-in account.',
                                style: TextStyle(
                                  fontSize: 12,
                                  color: InkWashColors.mutedInk,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(
                    title: 'Basic information',
                    subtitle:
                        'Information used for your account and trip experience',
                  ),
                  const SizedBox(height: 10),
                  field(
                    controller: name,
                    label: 'Full name',
                    icon: Icons.person_outline_rounded,
                    validator: (v) {
                      final val = (v ?? '').trim();
                      if (val.isEmpty) return 'Please enter your full name.';
                      if (!AuthService.validateFullName(val)) {
                        return 'Please enter a valid full name (letters required).';
                      }
                      return null;
                    },
                  ),
                  field(
                    controller: phone,
                    label: 'Phone number',
                    icon: Icons.phone_outlined,
                    keyboardType: TextInputType.phone,
                    hint: '+60 12-345 6789',
                    validator: (v) {
                      final val = (v ?? '').trim();
                      if (val.isEmpty) return null;
                      if (!RegExp(r'^\+?[0-9\s\-\(\)]{7,20}$')
                          .hasMatch(val)) {
                        return 'Enter a valid phone number.';
                      }
                      return null;
                    },
                  ),
                  field(
                    controller: dob,
                    label: 'Date of birth',
                    icon: Icons.cake_outlined,
                    hint: 'YYYY-MM-DD',
                    readOnly: true,
                    onTap: pickBirthDate,
                    suffix: const Icon(Icons.calendar_month_outlined),
                  ),
                  field(
                    controller: nationality,
                    label: 'Nationality',
                    icon: Icons.public_rounded,
                    hint: 'Select country / nationality',
                    readOnly: true,
                    onTap: pickNationality,
                    suffix: const Icon(Icons.arrow_drop_down_rounded),
                  ),
                  field(
                    controller: currentCity,
                    label: 'Current city',
                    icon: Icons.location_city_outlined,
                    hint: 'Select or enter city',
                    readOnly: true,
                    onTap: pickCurrentCity,
                    suffix: const Icon(Icons.arrow_drop_down_rounded),
                  ),
                  const SizedBox(height: 2),
                  DropdownButtonFormField<String>(
                    initialValue: gender,
                    items: genders
                        .map((e) => DropdownMenuItem(value: e, child: Text(e)))
                        .toList(),
                    onChanged: (v) => setState(() => gender = v ?? gender),
                    decoration: const InputDecoration(
                      labelText: 'Gender',
                      prefixIcon: Icon(Icons.badge_outlined),
                    ),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(
                    title: 'Emergency contact',
                    subtitle:
                        'Optional contact information for your own trip record',
                  ),
                  const SizedBox(height: 10),
                  field(
                    controller: emergencyName,
                    label: 'Contact name',
                    icon: Icons.person_pin_outlined,
                    validator: (v) {
                      final nameVal = (v ?? '').trim();
                      final phoneVal = emergencyPhone.text.trim();
                      if (phoneVal.isNotEmpty && nameVal.isEmpty) {
                        return 'Please enter emergency contact name.';
                      }
                      return null;
                    },
                  ),
                  field(
                    controller: emergencyPhone,
                    label: 'Contact phone',
                    icon: Icons.emergency_outlined,
                    keyboardType: TextInputType.phone,
                    hint: '+60 12-345 6789',
                    validator: (v) {
                      final phoneVal = (v ?? '').trim();
                      final nameVal = emergencyName.text.trim();
                      if (nameVal.isNotEmpty && phoneVal.isEmpty) {
                        return 'Please enter emergency contact phone.';
                      }
                      if (phoneVal.isNotEmpty &&
                          !RegExp(r'^\+?[0-9\s\-\(\)]{7,20}$')
                              .hasMatch(phoneVal)) {
                        return 'Enter a valid emergency contact phone.';
                      }
                      return null;
                    },
                  ),
                  DropdownButtonFormField<String>(
                    initialValue: emergencyRelationship,
                    items: relationships
                        .map((e) => DropdownMenuItem(value: e, child: Text(e)))
                        .toList(),
                    onChanged: (v) => setState(
                      () => emergencyRelationship = v ?? emergencyRelationship,
                    ),
                    decoration: const InputDecoration(
                      labelText: 'Relationship',
                      prefixIcon: Icon(Icons.group_outlined),
                    ),
                  ),
                  const SizedBox(height: 20),
                  const TravelSectionHeader(
                    title: 'About your travel style',
                    subtitle:
                        'A short profile note separate from the questionnaire',
                  ),
                  const SizedBox(height: 10),
                  field(
                    controller: travelBio,
                    label: 'Travel bio',
                    icon: Icons.edit_note_rounded,
                    maxLines: 4,
                    hint:
                        'e.g. I enjoy local food, museums and relaxed walking days.',
                  ),
                  const SizedBox(height: 14),
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

Future<String?> _showSearchablePicker({
  required BuildContext context,
  required String title,
  required List<String> items,
  required String currentValue,
  bool allowCustom = false,
  String customHint = 'Type custom value...',
}) {
  return showModalBottomSheet<String>(
    context: context,
    isScrollControlled: true,
    backgroundColor: Colors.white,
    shape: const RoundedRectangleBorder(
      borderRadius: BorderRadius.vertical(top: Radius.circular(22)),
    ),
    builder: (ctx) {
      return _SearchablePickerSheet(
        title: title,
        items: items,
        currentValue: currentValue,
        allowCustom: allowCustom,
        customHint: customHint,
      );
    },
  );
}

class _SearchablePickerSheet extends StatefulWidget {
  final String title;
  final List<String> items;
  final String currentValue;
  final bool allowCustom;
  final String customHint;

  const _SearchablePickerSheet({
    required this.title,
    required this.items,
    required this.currentValue,
    this.allowCustom = false,
    this.customHint = 'Type custom value...',
  });

  @override
  State<_SearchablePickerSheet> createState() => _SearchablePickerSheetState();
}

class _SearchablePickerSheetState extends State<_SearchablePickerSheet> {
  final searchController = TextEditingController();
  String query = '';

  @override
  void dispose() {
    searchController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final filtered = widget.items
        .where((e) => e.toLowerCase().contains(query.toLowerCase().trim()))
        .toList();
    final trimmedQuery = query.trim();
    final hasExactMatch = widget.items.any(
      (e) => e.toLowerCase() == trimmedQuery.toLowerCase(),
    );

    return DraggableScrollableSheet(
      initialChildSize: 0.75,
      minChildSize: 0.45,
      maxChildSize: 0.95,
      expand: false,
      builder: (context, scrollController) {
        return Padding(
          padding: EdgeInsets.only(
            bottom: MediaQuery.of(context).viewInsets.bottom,
          ),
          child: Column(
            children: [
              const SizedBox(height: 10),
              Container(
                width: 44,
                height: 5,
                decoration: BoxDecoration(
                  color: Colors.grey.shade300,
                  borderRadius: BorderRadius.circular(10),
                ),
              ),
              const SizedBox(height: 14),
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 18),
                child: Row(
                  children: [
                    Expanded(
                      child: Text(
                        widget.title,
                        style: const TextStyle(
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close_rounded),
                      onPressed: () => Navigator.pop(context),
                    ),
                  ],
                ),
              ),
              Padding(
                padding:
                    const EdgeInsets.symmetric(horizontal: 18, vertical: 8),
                child: TextField(
                  controller: searchController,
                  autofocus: false,
                  decoration: InputDecoration(
                    hintText: 'Search or filter...',
                    prefixIcon: const Icon(Icons.search_rounded),
                    suffixIcon: searchController.text.isNotEmpty
                        ? IconButton(
                            icon: const Icon(Icons.clear_rounded),
                            onPressed: () {
                              searchController.clear();
                              setState(() => query = '');
                            },
                          )
                        : null,
                  ),
                  onChanged: (val) => setState(() => query = val),
                ),
              ),
              Expanded(
                child: ListView.builder(
                  controller: scrollController,
                  itemCount: filtered.length +
                      (widget.allowCustom &&
                              trimmedQuery.isNotEmpty &&
                              !hasExactMatch
                          ? 1
                          : 0),
                  itemBuilder: (context, index) {
                    if (widget.allowCustom &&
                        trimmedQuery.isNotEmpty &&
                        !hasExactMatch &&
                        index == 0) {
                      return ListTile(
                        leading: const Icon(
                          Icons.add_circle_outline_rounded,
                          color: InkWashColors.blueGrey,
                        ),
                        title: Text(
                          'Use "$trimmedQuery"',
                          style: const TextStyle(fontWeight: FontWeight.w700),
                        ),
                        subtitle: const Text('Custom entry'),
                        onTap: () => Navigator.pop(context, trimmedQuery),
                      );
                    }
                    final adjustedIndex = (widget.allowCustom &&
                            trimmedQuery.isNotEmpty &&
                            !hasExactMatch)
                        ? index - 1
                        : index;
                    final item = filtered[adjustedIndex];
                    final isSelected = item.toLowerCase() ==
                        widget.currentValue.toLowerCase().trim();

                    return ListTile(
                      title: Text(
                        item,
                        style: TextStyle(
                          fontWeight:
                              isSelected ? FontWeight.w900 : FontWeight.w500,
                          color: isSelected
                              ? InkWashColors.blueGrey
                              : InkWashColors.ink,
                        ),
                      ),
                      trailing: isSelected
                          ? const Icon(
                              Icons.check_rounded,
                              color: InkWashColors.blueGrey,
                            )
                          : null,
                      onTap: () => Navigator.pop(context, item),
                    );
                  },
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}
