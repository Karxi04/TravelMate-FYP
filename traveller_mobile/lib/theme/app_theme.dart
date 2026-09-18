import 'package:flutter/material.dart';

class InkWashColors {
  static const charcoal = Color(0xFF4A4A4A);
  static const softGrey = Color(0xFFCBCBCB);
  static const cream = Color(0xFFFFFFE3);
  static const blueGrey = Color(0xFF6D8196);
  static const canvas = Color(0xFFF7F7F4);
  static const ink = Color(0xFF202020);
  static const mutedInk = Color(0xFF737373);
  static const paleBlue = Color(0xFFE8EDF1);
}

ThemeData buildInkWashTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: InkWashColors.blueGrey,
    brightness: Brightness.light,
  ).copyWith(
    primary: InkWashColors.blueGrey,
    secondary: InkWashColors.charcoal,
    surface: Colors.white,
    surfaceContainerHighest: InkWashColors.cream,
    outline: InkWashColors.softGrey,
  );

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    scaffoldBackgroundColor: InkWashColors.canvas,
    appBarTheme: const AppBarTheme(
      backgroundColor: InkWashColors.canvas,
      foregroundColor: InkWashColors.ink,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: TextStyle(
        color: InkWashColors.ink,
        fontSize: 22,
        fontWeight: FontWeight.w800,
      ),
    ),
    cardTheme: CardThemeData(
      color: Colors.white,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: Color(0xFFE3E3DE)),
        borderRadius: BorderRadius.circular(20),
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: Colors.white,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 15),
      border: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: InkWashColors.softGrey),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: Color(0xFFE1E1DC)),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: BorderRadius.circular(16),
        borderSide: const BorderSide(color: InkWashColors.blueGrey, width: 1.6),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: InkWashColors.blueGrey,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 15),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(16)),
      ),
    ),
    navigationBarTheme: const NavigationBarThemeData(
      height: 70,
      backgroundColor: Colors.white,
      indicatorColor: InkWashColors.cream,
      surfaceTintColor: Colors.transparent,
    ),
  );
}
