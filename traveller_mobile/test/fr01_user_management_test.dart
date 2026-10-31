import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/utils/country_city_data.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/edit_profile_screen.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/login_screen.dart';
import 'package:travelmate_traveller/modules/fr01_user_management/profile_details_screen.dart';
import 'package:travelmate_traveller/services/api_service.dart';
import 'package:travelmate_traveller/services/auth_service.dart';

class _MockAuthService extends AuthService {
  String? registeredName;
  String? registeredEmail;
  String? registeredPassword;
  String? loggedInEmail;
  String? loggedInPassword;
  Object? nextLoginError;
  Object? nextRegisterError;

  @override
  Future<void> registerTraveller({
    required String name,
    required String email,
    required String password,
  }) async {
    if (nextRegisterError != null) {
      final err = nextRegisterError!;
      nextRegisterError = null;
      throw err;
    }
    registeredName = name;
    registeredEmail = email;
    registeredPassword = password;
  }

  @override
  Future<void> loginTraveller(String email, String password) async {
    if (nextLoginError != null) {
      final err = nextLoginError!;
      nextLoginError = null;
      throw err;
    }
    loggedInEmail = email;
    loggedInPassword = password;
  }
}

class _MockProfileApi extends ApiService {
  Map<String, dynamic> storedProfile;
  final putCalls = <Map<String, dynamic>>[];
  Object? nextPutError;

  _MockProfileApi({Map<String, dynamic>? initialProfile})
      : storedProfile = initialProfile ??
            {
              'uid': 'test-traveller-123',
              'name': 'Original Name',
              'phoneNo': '+60123456789',
              'email': 'traveller@test.com',
              'dateOfBirth': '1995-05-15',
              'nationality': 'Malaysia',
              'currentCity': 'George Town',
              'gender': 'Female',
              'preferredLanguage': 'English',
              'emergencyContactName': 'Jane Doe',
              'emergencyContact': '+60198765432',
              'emergencyRelationship': 'Family',
              'travelBio': 'I love Penang food and beach walks.',
              'role': 'traveller',
              'status': 'active',
              'createdAt': '2026-08-20T11:08:01Z',
            };

  @override
  Future<dynamic> get(String path, [Map<String, String>? query]) async {
    if (path == '/api/fr1/me') {
      return {'ok': true, 'profile': Map<String, dynamic>.from(storedProfile)};
    }
    throw StateError('Unexpected GET $path');
  }

  @override
  Future<dynamic> put(String path, [Map<String, dynamic>? body]) async {
    if (path == '/api/fr1/me') {
      if (nextPutError != null) {
        final err = nextPutError!;
        nextPutError = null;
        throw err;
      }
      final payload = body ?? <String, dynamic>{};
      putCalls.add(Map<String, dynamic>.from(payload));
      storedProfile = {...storedProfile, ...payload};
      return {'ok': true, 'profile': Map<String, dynamic>.from(storedProfile)};
    }
    throw StateError('Unexpected PUT $path');
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('FR1 Validation Logic & Password Requirements', () {
    test('FR1-02: Numeric-only passwords must be rejected', () {
      expect(
        AuthService.validateRegistrationPasswordRequirement('123456'),
        'Password must be at least 8 characters.',
      );
      expect(
        AuthService.validateRegistrationPasswordRequirement('12345678'),
        'Include at least one letter, one number and one symbol.',
      );
      expect(
        AuthService.validateRegistrationPasswordRequirement('password123'),
        'Include at least one letter, one number and one symbol.',
      );
    });

    test('FR1-03: Letter + number + symbol password is accepted', () {
      expect(
        AuthService.validateRegistrationPasswordRequirement('Password123!'),
        isNull,
      );
      expect(
        AuthService.validateRegistrationPasswordRequirement('Travel@2026'),
        isNull,
      );
      expect(
        AuthService.validateRegistrationPasswordRequirement('P@ssw0rd#2026'),
        isNull,
      );
    });

    test('FR1-04: Invalid email format rejected', () {
      expect(AuthService.validateEmailFormat('usergmail.com'), isFalse);
      expect(AuthService.validateEmailFormat('user@'), isFalse);
      expect(AuthService.validateEmailFormat('@gmail.com'), isFalse);
      expect(AuthService.validateEmailFormat('user name@gmail.com'), isFalse);
      expect(AuthService.validateEmailFormat('   '), isFalse);
    });

    test('FR1-05: Valid non-Gmail email addresses are accepted', () {
      expect(AuthService.validateEmailFormat('traveller@gmail.com'), isTrue);
      expect(AuthService.validateEmailFormat('traveller@outlook.com'), isTrue);
      expect(AuthService.validateEmailFormat('traveller@yahoo.com'), isTrue);
      expect(
        AuthService.validateEmailFormat('student@university.edu.my'),
        isTrue,
      );
      expect(AuthService.validateEmailFormat('employee@company.com'), isTrue);
    });

    test('FR1-06: Numeric-only and whitespace-only full names rejected', () {
      expect(AuthService.validateFullName('123456'), isFalse);
      expect(AuthService.validateFullName('   '), isFalse);
      expect(AuthService.validateFullName(''), isFalse);
      expect(AuthService.validateFullName('123-456'), isFalse);
      expect(AuthService.validateFullName('!@#\$%^'), isFalse);
    });

    test('FR1-07: Mixed letter-and-number full names accepted', () {
      expect(AuthService.validateFullName('Ali123'), isTrue);
      expect(AuthService.validateFullName('Traveller99'), isTrue);
    });

    test('FR1-08: Unicode, international and punctuated names accepted', () {
      expect(AuthService.validateFullName('Ali Tan'), isTrue);
      expect(AuthService.validateFullName('王小明'), isTrue);
      expect(AuthService.validateFullName('Anne-Marie'), isTrue);
      expect(AuthService.validateFullName("O'Connor"), isTrue);
      expect(AuthService.validateFullName('José González'), isTrue);
    });

    test('FR1-09: Auth error formatter yields safe, non-enumerating messages', () {
      expect(
        AuthService.formatAuthError(
          Exception('invalid-credential'),
        ),
        'Incorrect email or password. Please check your details and try again.',
      );
      expect(
        AuthService.formatAuthError(Exception('network connection error')),
        'Unable to connect. Check your internet connection and try again.',
      );
    });
  });

  group('FR1 Login & Registration Screen UX', () {
    testWidgets('FR1-01 & FR1-03: Valid registration calls registerTraveller',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockAuth = _MockAuthService();
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(auth: mockAuth),
        ),
      );

      // Switch to register mode
      await tester.tap(find.text('New to TravelMate? Create account'));
      await tester.pumpAndSettle();

      expect(find.text('Create traveller account'), findsOneWidget);
      expect(find.text('Confirm password'), findsOneWidget);

      // Enter registration details
      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), 'Ali Tan'); // name
      await tester.enterText(fields.at(1), 'traveller@outlook.com'); // email
      await tester.enterText(fields.at(2), 'Travel@2026'); // password
      await tester.enterText(fields.at(3), 'Travel@2026'); // confirm password

      await tester.ensureVisible(find.text('Create account'));
      await tester.tap(find.text('Create account'));
      await tester.pumpAndSettle();

      expect(mockAuth.registeredName, 'Ali Tan');
      expect(mockAuth.registeredEmail, 'traveller@outlook.com');
      expect(mockAuth.registeredPassword, 'Travel@2026');
    });

    testWidgets('FR1-02: Registering with 6-digit password displays error',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockAuth = _MockAuthService();
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(auth: mockAuth),
        ),
      );

      // Switch to register mode
      await tester.tap(find.text('New to TravelMate? Create account'));
      await tester.pumpAndSettle();

      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), 'Ali Tan');
      await tester.enterText(fields.at(1), 'traveller@gmail.com');
      await tester.enterText(fields.at(2), '123456');
      await tester.enterText(fields.at(3), '123456');

      await tester.ensureVisible(find.text('Create account'));
      await tester.tap(find.text('Create account'));
      await tester.pumpAndSettle();

      expect(find.text('Password must be at least 8 characters.'), findsOneWidget);
      expect(mockAuth.registeredName, isNull);
    });

    testWidgets('FR1-06: Registering with numeric name displays error',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockAuth = _MockAuthService();
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(auth: mockAuth),
        ),
      );

      // Switch to register mode
      await tester.tap(find.text('New to TravelMate? Create account'));
      await tester.pumpAndSettle();

      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), '123456');
      await tester.enterText(fields.at(1), 'traveller@gmail.com');
      await tester.enterText(fields.at(2), 'Travel@2026');
      await tester.enterText(fields.at(3), 'Travel@2026');

      await tester.ensureVisible(find.text('Create account'));
      await tester.tap(find.text('Create account'));
      await tester.pumpAndSettle();

      expect(
        find.text('Please enter a valid full name (letters required).'),
        findsOneWidget,
      );
      expect(mockAuth.registeredName, isNull);
    });

    testWidgets('FR1-22: Existing login with older password succeeds',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockAuth = _MockAuthService();
      await tester.pumpWidget(
        MaterialApp(
          home: LoginScreen(auth: mockAuth),
        ),
      );

      final fields = find.byType(TextField);
      await tester.enterText(fields.at(0), 'existing@domain.com');
      await tester.enterText(fields.at(1), '123456'); // older short password

      await tester.ensureVisible(find.text('Sign in'));
      await tester.tap(find.text('Sign in'));
      await tester.pumpAndSettle();

      expect(mockAuth.loggedInEmail, 'existing@domain.com');
      expect(mockAuth.loggedInPassword, '123456');
    });
  });

  group('FR1 Edit Profile & Persistence UX', () {
    testWidgets('FR1-21: Preferred Language is removed from Edit Profile UI',
        (tester) async {
      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Preferred language'), findsNothing);
      expect(find.text('Preferred Language'), findsNothing);
    });

    testWidgets('FR1-21: Preferred Language is removed from Profile Details UI',
        (tester) async {
      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: ProfileDetailsScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Preferred language'), findsNothing);
      expect(find.text('Preferred Language'), findsNothing);
    });

    testWidgets('FR1-10 to FR1-16: Edit Profile Save submits complete payload',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      // Verify initial fields populated from GET /api/fr1/me
      expect(find.text('Original Name'), findsOneWidget);
      expect(find.text('+60123456789'), findsOneWidget);
      expect(find.text('1995-05-15'), findsOneWidget);
      expect(find.text('Malaysia'), findsOneWidget);
      expect(find.text('George Town'), findsOneWidget);

      // Edit name
      final nameField = find.widgetWithText(TextFormField, 'Original Name');
      await tester.enterText(nameField, 'Updated Traveller Name');

      // Tap save
      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      // Verify payload sent to PUT /api/fr1/me
      expect(mockApi.putCalls, hasLength(1));
      final sent = mockApi.putCalls.first;
      expect(sent['name'], 'Updated Traveller Name');
      expect(sent['phoneNo'], '+60123456789');
      expect(sent['dateOfBirth'], '1995-05-15');
      expect(sent['nationality'], 'Malaysia');
      expect(sent['currentCity'], 'George Town');
      expect(sent['gender'], 'Female');
      expect(sent['emergencyContactName'], 'Jane Doe');
      expect(sent['emergencyContact'], '+60198765432');
      expect(sent['emergencyRelationship'], 'Family');
      expect(sent['travelBio'], 'I love Penang food and beach walks.');
      expect(sent['preferredLanguage'], 'English'); // Preserved in payload
    });

    testWidgets('FR1-17: Save failure preserves user inputs without closing',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      mockApi.nextPutError = Exception('Network error');

      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      final nameField = find.widgetWithText(TextFormField, 'Original Name');
      await tester.enterText(nameField, 'Newly Typed Name');

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      // Error shown, but screen remains open and user input is preserved
      expect(find.text('Newly Typed Name'), findsOneWidget);
      expect(find.text('Edit profile'), findsOneWidget);
    });

    testWidgets('FR1-12 & FR1-13: Nationality & City Pickers display datasets',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      // Tap Nationality via its unique public icon
      await tester.tap(find.byIcon(Icons.public_rounded));
      await tester.pumpAndSettle();

      expect(find.text('Select nationality / country'), findsOneWidget);
      expect(find.text('Malaysia'), findsWidgets);
      expect(find.text('Singapore'), findsOneWidget);

      // Close sheet
      await tester.tap(find.byIcon(Icons.close_rounded));
      await tester.pumpAndSettle();

      // Tap Current City via its location city icon
      await tester.tap(find.byIcon(Icons.location_city_outlined));
      await tester.pumpAndSettle();

      expect(find.text('Select city (Malaysia)'), findsOneWidget);
      expect(find.text('George Town'), findsWidgets);
      expect(find.text('Kuala Lumpur'), findsOneWidget);
    });
  });

  group('FR1 Country-Dependent City Selection (FR1-CITY-01 to FR1-CITY-08)', () {
    test('FR1-CITY-01: Malaysia country returns comprehensive Malaysian cities', () {
      final cities = CountryCityData.getCitiesForCountry('Malaysia');
      expect(cities, contains('Kuala Lumpur'));
      expect(cities, contains('George Town'));
      expect(cities, contains('Johor Bahru'));
      expect(cities, contains('Ipoh'));
      expect(cities, contains('Kota Kinabalu'));
      expect(cities, contains('Kuching'));
      expect(cities.length, greaterThanOrEqualTo(30));
    });

    test('FR1-CITY-02: Japan country returns Tokyo, Osaka, Kyoto, etc.', () {
      final cities = CountryCityData.getCitiesForCountry('Japan');
      expect(cities, contains('Tokyo'));
      expect(cities, contains('Osaka'));
      expect(cities, contains('Kyoto'));
      expect(cities, contains('Yokohama'));
      expect(cities, contains('Sapporo'));
    });

    test('FR1-CITY-03: China country returns Beijing, Shanghai, Guangzhou, etc.', () {
      final cities = CountryCityData.getCitiesForCountry('China');
      expect(cities, contains('Beijing'));
      expect(cities, contains('Shanghai'));
      expect(cities, contains('Guangzhou'));
      expect(cities, contains('Shenzhen'));
      expect(cities, contains('Chengdu'));
    });

    test('FR1-CITY-04: Australia country returns Sydney, Melbourne, Brisbane, etc.', () {
      final cities = CountryCityData.getCitiesForCountry('Australia');
      expect(cities, contains('Sydney'));
      expect(cities, contains('Melbourne'));
      expect(cities, contains('Brisbane'));
      expect(cities, contains('Perth'));
    });

    test('FR1-CITY-05: Singapore country returns Singapore', () {
      final cities = CountryCityData.getCitiesForCountry('Singapore');
      expect(cities, contains('Singapore'));
      expect(cities, hasLength(1));
    });

    testWidgets(
        'FR1-CITY-06: Switching country from Malaysia to Japan clears George Town',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('Malaysia'), findsOneWidget);
      expect(find.text('George Town'), findsOneWidget);

      // Open Nationality picker
      await tester.tap(find.byIcon(Icons.public_rounded));
      await tester.pumpAndSettle();

      // Filter for Japan
      final searchField = find.byType(TextField).last;
      await tester.enterText(searchField, 'Japan');
      await tester.pumpAndSettle();

      // Tap Japan
      await tester.tap(find.text('Japan').last);
      await tester.pumpAndSettle();

      expect(find.text('Japan'), findsOneWidget);
      expect(find.text('George Town'), findsNothing);
    });

    testWidgets(
        'FR1-CITY-07: Custom international city entry allows typing custom city',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      // Tap Current City picker
      await tester.tap(find.byIcon(Icons.location_city_outlined));
      await tester.pumpAndSettle();

      // Type a custom city name not in list: "Monte Carlo"
      final searchField = find.byType(TextField).last;
      await tester.enterText(searchField, 'Monte Carlo');
      await tester.pumpAndSettle();

      expect(find.text('Use "Monte Carlo"'), findsOneWidget);
      await tester.tap(find.text('Use "Monte Carlo"'));
      await tester.pumpAndSettle();

      expect(find.text('Monte Carlo'), findsOneWidget);
    });

    testWidgets('FR1-CITY-08: Saved country and city load correctly on reload',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi(initialProfile: {
        'name': 'International Traveller',
        'nationality': 'Japan',
        'currentCity': 'Kyoto',
        'dateOfBirth': '1990-01-01',
        'gender': 'Male',
        'phoneNo': '+819012345678',
        'emergencyContactName': 'Kenji',
        'emergencyContact': '+819098765432',
        'emergencyRelationship': 'Friend',
        'travelBio': 'Exploring temples and nature.',
        'preferredLanguage': 'Japanese',
      });

      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      expect(find.text('International Traveller'), findsOneWidget);
      expect(find.text('Japan'), findsOneWidget);
      expect(find.text('Kyoto'), findsOneWidget);
      expect(find.text('Male'), findsOneWidget);
      expect(find.text('Kenji'), findsOneWidget);
      expect(find.text('+819098765432'), findsOneWidget);
      expect(find.text('Friend'), findsOneWidget);
      expect(find.text('Exploring temples and nature.'), findsOneWidget);
    });
  });

  group('FR1 Profile Save & Full-Stack Persistence (FR1-SAVE-01 to FR1-SAVE-18)', () {
    testWidgets('FR1-SAVE-01 to 11: All profile fields correctly captured in save payload',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      expect(mockApi.putCalls, hasLength(1));
      final payload = mockApi.putCalls.first;

      // FR1-SAVE-01 Name
      expect(payload['name'], 'Original Name');
      // FR1-SAVE-02 Phone
      expect(payload['phoneNo'], '+60123456789');
      // FR1-SAVE-03 Date of Birth
      expect(payload['dateOfBirth'], '1995-05-15');
      // FR1-SAVE-04 Nationality
      expect(payload['nationality'], 'Malaysia');
      // FR1-SAVE-05 Current City
      expect(payload['currentCity'], 'George Town');
      // FR1-SAVE-06 Gender
      expect(payload['gender'], 'Female');
      // FR1-SAVE-07 Emergency Contact Name
      expect(payload['emergencyContactName'], 'Jane Doe');
      // FR1-SAVE-08 Emergency Contact Phone
      expect(payload['emergencyContact'], '+60198765432');
      // FR1-SAVE-09 Emergency Relationship
      expect(payload['emergencyRelationship'], 'Family');
      // FR1-SAVE-10 Travel Bio
      expect(payload['travelBio'], 'I love Penang food and beach walks.');
      // FR1-SAVE-11 Preferred Language preserved
      expect(payload['preferredLanguage'], 'English');
    });

    testWidgets('FR1-SAVE-12 to 14: Client payload excludes protected metadata',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      final payload = mockApi.putCalls.first;
      // FR1-SAVE-12: role is never submitted by client
      expect(payload.containsKey('role'), isFalse);
      // FR1-SAVE-13: uid is never submitted by client
      expect(payload.containsKey('uid'), isFalse);
      // FR1-SAVE-14: email is never submitted by client
      expect(payload.containsKey('email'), isFalse);
    });

    testWidgets('FR1-SAVE-15: Empty name blocks form submission',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      final nameField = find.widgetWithText(TextFormField, 'Original Name');
      await tester.enterText(nameField, '');

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      expect(find.text('Please enter your full name.'), findsOneWidget);
      expect(mockApi.putCalls, isEmpty);
    });

    testWidgets('FR1-SAVE-16: Malformed phone blocks form submission',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      final phoneField = find.widgetWithText(TextFormField, '+60123456789');
      await tester.enterText(phoneField, 'not-a-phone');

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      expect(find.text('Enter a valid phone number.'), findsOneWidget);
      expect(mockApi.putCalls, isEmpty);
    });

    testWidgets(
        'FR1-SAVE-17 & 18: Incomplete emergency contact blocks form submission',
        (tester) async {
      tester.view.physicalSize = const Size(1080, 2400);
      tester.view.devicePixelRatio = 1.0;
      addTearDown(() => tester.view.resetPhysicalSize());

      final mockApi = _MockProfileApi();
      await tester.pumpWidget(
        MaterialApp(
          home: EditProfileScreen(api: mockApi),
        ),
      );
      await tester.pumpAndSettle();

      // Clear emergency phone while keeping contact name
      final phoneField = find.widgetWithText(TextFormField, '+60198765432');
      await tester.enterText(phoneField, '');

      await tester.ensureVisible(find.text('Save changes'));
      await tester.tap(find.text('Save changes'));
      await tester.pumpAndSettle();

      // FR1-SAVE-18: emergency phone missing when name provided
      expect(
        find.text('Please enter emergency contact phone.'),
        findsOneWidget,
      );
      expect(mockApi.putCalls, isEmpty);
    });
  });
}
