import 'package:firebase_auth/firebase_auth.dart';

import 'api_service.dart';

class AuthService {
  final FirebaseAuth _auth = FirebaseAuth.instance;
  final ApiService _api = ApiService();

  Stream<User?> get authChanges => _auth.authStateChanges();
  User? get currentUser => _auth.currentUser;

  bool validateRequiredInformation(Map<String, String> data) =>
      data.values.every((value) => value.trim().isNotEmpty);

  bool validateEmailFormat(String email) =>
      RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(email.trim());

  bool validatePasswordRequirement(String password) => password.length >= 6;

  bool validateLoginInput(String email, String password) =>
      validateEmailFormat(email) && password.isNotEmpty;

  bool validateEmailAddress(String email) => validateEmailFormat(email);

  Future<UserCredential> createUserAccount(String email, String password) =>
      _auth.createUserWithEmailAndPassword(
        email: email.trim(),
        password: password,
      );

  Future<UserCredential> authenticateCredentials(
    String email,
    String password,
  ) =>
      _auth.signInWithEmailAndPassword(
        email: email.trim(),
        password: password,
      );

  Future<void> sendPasswordResetEmail(String email) =>
      _auth.sendPasswordResetEmail(email: email.trim());

  Future<void> signOutUser() => _auth.signOut();

  Future<void> registerTraveller({
    required String name,
    required String email,
    required String password,
  }) async {
    final info = {'name': name, 'email': email, 'password': password};
    if (!validateRequiredInformation(info) ||
        !validateEmailFormat(email) ||
        !validatePasswordRequirement(password)) {
      throw Exception('Invalid registration information.');
    }

    final credential = await createUserAccount(email, password);
    await credential.user?.updateDisplayName(name.trim());
    await credential.user?.getIdToken(true);

    try {
      await _api.post(
        '/api/fr1/profile',
        {'role': 'traveller', 'name': name.trim()},
      );
    } catch (e) {
      // Authentication remains valid. ApiService will normally persist the
      // profile locally when the cloud backend is unavailable.
      rethrow;
    }
  }

  Future<void> loginTraveller(String email, String password) async {
    if (!validateLoginInput(email, password)) {
      throw Exception('Enter a valid email and password.');
    }
    await authenticateCredentials(email, password);
    final result = await _api.get('/api/fr1/me');
    final profile = result['profile'];
    if (profile != null && profile['status'] == 'deactivated') {
      await signOutUser();
      throw Exception('This account is deactivated.');
    }
    if (profile != null && profile['role'] != 'traveller') {
      await signOutUser();
      throw Exception('This account is not a Traveller account.');
    }
  }

  Future<void> resetPassword(String email) async {
    if (!validateEmailAddress(email)) {
      throw Exception('Enter a valid email address.');
    }
    await sendPasswordResetEmail(email);
  }

  Future<void> logout() => signOutUser();
}
