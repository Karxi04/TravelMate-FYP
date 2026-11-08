import 'package:firebase_auth/firebase_auth.dart';

import 'api_service.dart';
import 'android_push_service.dart';

class AuthService {
  final FirebaseAuth? _authOverride;
  final ApiService? _apiOverride;

  AuthService({FirebaseAuth? auth, ApiService? api})
      : _authOverride = auth,
        _apiOverride = api;

  FirebaseAuth get _auth => _authOverride ?? FirebaseAuth.instance;
  ApiService get _api => _apiOverride ?? ApiService();

  Stream<User?> get authChanges => _auth.authStateChanges();
  User? get currentUser => _auth.currentUser;

  static bool validateFullName(String? name) {
    final trimmed = (name ?? '').trim();
    if (trimmed.isEmpty) return false;
    final hasLetter = RegExp(r'\p{L}', unicode: true).hasMatch(trimmed);
    if (!hasLetter) return false;
    return RegExp(r"^[\p{L}0-9\s'’.\-]+$", unicode: true).hasMatch(trimmed);
  }

  static String? validateRegistrationPasswordRequirement(String? password) {
    final p = password ?? '';
    if (p.isEmpty) return 'Please enter your password.';
    if (p.length < 8) return 'Password must be at least 8 characters.';
    final hasLetter = RegExp(r'[a-zA-Z]').hasMatch(p);
    final hasDigit = RegExp(r'[0-9]').hasMatch(p);
    final hasSymbol = RegExp(r'[^a-zA-Z0-9\s]').hasMatch(p);
    if (!hasLetter || !hasDigit || !hasSymbol) {
      return 'Include at least one letter, one number and one symbol.';
    }
    return null;
  }

  static String formatAuthError(Object error) {
    if (error is FirebaseAuthException) {
      switch (error.code) {
        case 'invalid-credential':
        case 'wrong-password':
        case 'user-not-found':
          return 'Incorrect email or password. Please check your details and try again.';
        case 'invalid-email':
          return 'Please enter a valid email address.';
        case 'user-disabled':
          return 'This account is unavailable. Please contact support.';
        case 'too-many-requests':
          return 'Too many attempts. Please try again later or reset your password.';
        case 'network-request-failed':
          return 'Unable to connect. Check your internet connection and try again.';
        case 'email-already-in-use':
          return 'An account with this email already exists. Please sign in instead.';
        case 'weak-password':
          return 'Password does not meet the security requirements.';
        case 'operation-not-allowed':
          return 'This sign-in method is currently disabled.';
        default:
          return 'Authentication failed. Please check your details and try again.';
      }
    }
    final str = error.toString();
    if (str.contains('invalid-credential') ||
        str.contains('wrong-password') ||
        str.contains('user-not-found')) {
      return 'Incorrect email or password. Please check your details and try again.';
    }
    if (str.contains('invalid-email')) {
      return 'Please enter a valid email address.';
    }
    if (str.contains('user-disabled')) {
      return 'This account is unavailable. Please contact support.';
    }
    if (str.contains('too-many-requests')) {
      return 'Too many attempts. Please try again later or reset your password.';
    }
    if (isBackendConnectionFailure(error) ||
        str.contains('network') ||
        str.contains('connection') ||
        str.contains('timed out')) {
      return 'Unable to connect. Check your internet connection and try again.';
    }
    final msg = str.replaceFirst(RegExp(r'^Exception:\s*'), '').trim();
    return msg.isNotEmpty ? msg : 'Something went wrong. Please try again.';
  }

  bool validateRequiredInformation(Map<String, String> data) =>
      data.values.every((value) => value.trim().isNotEmpty);

  static bool validateEmailFormat(String email) =>
      RegExp(r'^[^@\s]+@[^@\s]+\.[^@\s]+$').hasMatch(email.trim());

  bool validatePasswordRequirement(String password) =>
      validateRegistrationPasswordRequirement(password) == null;

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
    if (!validateFullName(name)) {
      throw Exception('Please enter a valid full name (letters required).');
    }
    if (!validateEmailFormat(email)) {
      throw Exception('Please enter a valid email address.');
    }
    final passwordError = validateRegistrationPasswordRequirement(password);
    if (passwordError != null) {
      throw Exception(passwordError);
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

  Future<void> logout() async {
    await AndroidPushService.instance.beforeLogout();
    await signOutUser();
  }
}
