import 'package:flutter/material.dart';
import '../../services/api_service.dart';
import '../../services/auth_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';

class LoginScreen extends StatefulWidget {
  final AuthService? auth;
  final ApiService? api;

  const LoginScreen({super.key, this.auth, this.api});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  final email = TextEditingController();
  final password = TextEditingController();
  final confirmPassword = TextEditingController();
  final name = TextEditingController();
  late final AuthService auth = widget.auth ?? AuthService();

  bool registerMode = false;
  bool busy = false;
  bool showPassword = false;
  bool showConfirmPassword = false;

  Future<void> submit() async {
    final emailText = email.text.trim();
    final passwordText = password.text;

    if (registerMode) {
      final nameText = name.text.trim();
      if (nameText.isEmpty) {
        showError(context, 'Please enter your full name.');
        return;
      }
      if (!AuthService.validateFullName(nameText)) {
        showError(context, 'Please enter a valid full name (letters required).');
        return;
      }
      if (emailText.isEmpty) {
        showError(context, 'Please enter your email address.');
        return;
      }
      if (!AuthService.validateEmailFormat(emailText)) {
        showError(context, 'Please enter a valid email address.');
        return;
      }
      final passwordError =
          AuthService.validateRegistrationPasswordRequirement(passwordText);
      if (passwordError != null) {
        showError(context, passwordError);
        return;
      }
      if (confirmPassword.text.isEmpty) {
        showError(context, 'Please confirm your password.');
        return;
      }
      if (passwordText != confirmPassword.text) {
        showError(context, 'Passwords do not match.');
        return;
      }
    } else {
      if (emailText.isEmpty) {
        showError(context, 'Please enter your email address.');
        return;
      }
      if (!AuthService.validateEmailFormat(emailText)) {
        showError(context, 'Please enter a valid email address.');
        return;
      }
      if (passwordText.isEmpty) {
        showError(context, 'Please enter your password.');
        return;
      }
    }

    setState(() => busy = true);
    try {
      if (registerMode) {
        await auth.registerTraveller(
          name: name.text.trim(),
          email: emailText,
          password: passwordText,
        );
      } else {
        await auth.loginTraveller(emailText, passwordText);
      }
    } catch (e) {
      if (mounted) {
        showError(context, AuthService.formatAuthError(e));
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  Future<void> reset() async {
    final emailText = email.text.trim();
    if (emailText.isEmpty) {
      showError(context, 'Please enter your email address.');
      return;
    }
    if (!AuthService.validateEmailFormat(emailText)) {
      showError(context, 'Please enter a valid email address.');
      return;
    }
    try {
      await auth.resetPassword(emailText);
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Password reset email sent.')),
        );
      }
    } catch (e) {
      if (mounted) showError(context, AuthService.formatAuthError(e));
    }
  }

  @override
  void dispose() {
    email.dispose();
    password.dispose();
    confirmPassword.dispose();
    name.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(22),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Align(
                    alignment: Alignment.centerLeft,
                    child: Container(
                      width: 66,
                      height: 66,
                      decoration: BoxDecoration(
                        color: InkWashColors.blueGrey,
                        borderRadius: BorderRadius.circular(21),
                      ),
                      child: const Icon(
                        Icons.travel_explore_rounded,
                        color: Colors.white,
                        size: 32,
                      ),
                    ),
                  ),
                  const SizedBox(height: 16),
                  const Text(
                    'TravelMate',
                    style: TextStyle(
                      fontSize: 35,
                      fontWeight: FontWeight.w900,
                      color: InkWashColors.ink,
                    ),
                  ),
                  const SizedBox(height: 5),
                  const Text(
                    'Search, personalise and organise your trip in one place.',
                    style: TextStyle(color: InkWashColors.mutedInk),
                  ),
                  const SizedBox(height: 24),
                  InkCard(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.stretch,
                      children: [
                        Text(
                          registerMode
                              ? 'Create traveller account'
                              : 'Welcome back',
                          style: const TextStyle(
                            fontSize: 22,
                            fontWeight: FontWeight.w900,
                          ),
                        ),
                        const SizedBox(height: 15),
                        if (registerMode) ...[
                          TextField(
                            controller: name,
                            decoration: const InputDecoration(
                              labelText: 'Full name',
                              prefixIcon: Icon(Icons.person_outline_rounded),
                            ),
                          ),
                          const SizedBox(height: 10),
                        ],
                        TextField(
                          controller: email,
                          keyboardType: TextInputType.emailAddress,
                          decoration: const InputDecoration(
                            labelText: 'Email address',
                            prefixIcon: Icon(Icons.email_outlined),
                          ),
                        ),
                        const SizedBox(height: 10),
                        TextField(
                          controller: password,
                          obscureText: !showPassword,
                          onSubmitted: (_) => submit(),
                          decoration: InputDecoration(
                            labelText: 'Password',
                            prefixIcon: const Icon(Icons.lock_outline_rounded),
                            suffixIcon: IconButton(
                              onPressed: () =>
                                  setState(() => showPassword = !showPassword),
                              icon: Icon(
                                showPassword
                                    ? Icons.visibility_off_outlined
                                    : Icons.visibility_outlined,
                              ),
                            ),
                          ),
                        ),
                        if (registerMode) ...[
                          const SizedBox(height: 10),
                          TextField(
                            controller: confirmPassword,
                            obscureText: !showConfirmPassword,
                            onSubmitted: (_) => submit(),
                            decoration: InputDecoration(
                              labelText: 'Confirm password',
                              prefixIcon:
                                  const Icon(Icons.lock_outline_rounded),
                              suffixIcon: IconButton(
                                onPressed: () => setState(() =>
                                    showConfirmPassword = !showConfirmPassword),
                                icon: Icon(
                                  showConfirmPassword
                                      ? Icons.visibility_off_outlined
                                      : Icons.visibility_outlined,
                                ),
                              ),
                            ),
                          ),
                        ],
                        const SizedBox(height: 14),
                        FilledButton(
                          onPressed: busy ? null : submit,
                          child: Text(
                            busy
                                ? 'Please wait...'
                                : registerMode
                                    ? 'Create account'
                                    : 'Sign in',
                          ),
                        ),
                        if (!registerMode)
                          TextButton(
                            onPressed: busy ? null : reset,
                            child: const Text('Forgot password?'),
                          ),
                        const Divider(),
                        TextButton(
                          onPressed: busy
                              ? null
                              : () =>
                                  setState(() => registerMode = !registerMode),
                          child: Text(
                            registerMode
                                ? 'Already have an account? Sign in'
                                : 'New to TravelMate? Create account',
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
