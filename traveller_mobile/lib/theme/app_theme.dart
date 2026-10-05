import 'package:flutter/material.dart';

/// Semantic colours for the TravelMate Ink Wash visual language.
///
/// Screens should prefer these role-based names over one-off colour values so
/// loading, fallback, success, warning and error states remain consistent.
class AppColors {
  static const background = Color(0xFFF7F7F4);
  static const surface = Colors.white;
  static const surfaceElevated = Color(0xFFFCFCF9);

  static const primary = Color(0xFF6D8196);
  static const primaryStrong = Color(0xFF4F6479);
  static const primarySoft = Color(0xFFE8EDF1);

  static const textPrimary = Color(0xFF202020);
  static const textSecondary = Color(0xFF676A6D);
  static const divider = Color(0xFFE1E1DC);
  static const disabled = Color(0xFF9C9C98);

  static const success = Color(0xFF39745B);
  static const successSoft = Color(0xFFE5F2EA);
  static const warning = Color(0xFF8A6224);
  static const warningSoft = Color(0xFFFFF1D7);
  static const error = Color(0xFFA83E3E);
  static const errorSoft = Color(0xFFFBE7E7);
  static const info = Color(0xFF4F6F8E);
  static const infoSoft = Color(0xFFE7EFF6);
}

/// Backwards-compatible Ink Wash aliases used by existing screens.
class InkWashColors {
  static const charcoal = Color(0xFF4A4A4A);
  static const softGrey = Color(0xFFCBCBCB);
  static const cream = Color(0xFFFFFFE3);
  static const blueGrey = AppColors.primary;
  static const canvas = AppColors.background;
  static const ink = AppColors.textPrimary;
  static const mutedInk = AppColors.textSecondary;
  static const paleBlue = AppColors.primarySoft;
}

class AppSpacing {
  static const xxs = 4.0;
  static const xs = 8.0;
  static const sm = 12.0;
  static const md = 16.0;
  static const lg = 20.0;
  static const xl = 24.0;
  static const xxl = 32.0;

  static const page = EdgeInsets.symmetric(horizontal: md, vertical: lg);
  static const card = EdgeInsets.all(md);
}

class AppRadii {
  static const small = 10.0;
  static const medium = 14.0;
  static const large = 20.0;
  static const pill = 999.0;

  static final card = BorderRadius.circular(large);
  static final control = BorderRadius.circular(medium);
}

class AppSizes {
  static const minimumTapTarget = 48.0;
  static const iconSmall = 18.0;
  static const icon = 22.0;
  static const iconLarge = 28.0;
  static const navigationBar = 70.0;
  static const destinationImageAspectRatio = 16 / 9;
}

TextTheme buildTravelMateTextTheme() {
  return const TextTheme(
    displaySmall:
        TextStyle(fontSize: 36, height: 1.12, fontWeight: FontWeight.w800),
    headlineLarge:
        TextStyle(fontSize: 28, height: 1.18, fontWeight: FontWeight.w800),
    headlineMedium:
        TextStyle(fontSize: 24, height: 1.2, fontWeight: FontWeight.w800),
    headlineSmall:
        TextStyle(fontSize: 20, height: 1.25, fontWeight: FontWeight.w700),
    titleLarge:
        TextStyle(fontSize: 18, height: 1.3, fontWeight: FontWeight.w700),
    titleMedium:
        TextStyle(fontSize: 16, height: 1.35, fontWeight: FontWeight.w700),
    titleSmall:
        TextStyle(fontSize: 14, height: 1.35, fontWeight: FontWeight.w700),
    bodyLarge:
        TextStyle(fontSize: 16, height: 1.5, fontWeight: FontWeight.w400),
    bodyMedium:
        TextStyle(fontSize: 14, height: 1.45, fontWeight: FontWeight.w400),
    bodySmall:
        TextStyle(fontSize: 13, height: 1.4, fontWeight: FontWeight.w400),
    labelLarge:
        TextStyle(fontSize: 14, height: 1.2, fontWeight: FontWeight.w700),
    labelMedium:
        TextStyle(fontSize: 13, height: 1.2, fontWeight: FontWeight.w600),
  ).apply(
    bodyColor: AppColors.textPrimary,
    displayColor: AppColors.textPrimary,
  );
}

ThemeData buildInkWashTheme() {
  final scheme = ColorScheme.fromSeed(
    seedColor: AppColors.primary,
    brightness: Brightness.light,
  ).copyWith(
    primary: AppColors.primary,
    onPrimary: Colors.white,
    secondary: InkWashColors.charcoal,
    surface: AppColors.surface,
    surfaceContainerHighest: InkWashColors.cream,
    error: AppColors.error,
    outline: AppColors.divider,
  );

  final controlShape = RoundedRectangleBorder(borderRadius: AppRadii.control);

  return ThemeData(
    useMaterial3: true,
    colorScheme: scheme,
    textTheme: buildTravelMateTextTheme(),
    scaffoldBackgroundColor: AppColors.background,
    dividerColor: AppColors.divider,
    disabledColor: AppColors.disabled,
    appBarTheme: AppBarTheme(
      backgroundColor: AppColors.background,
      foregroundColor: AppColors.textPrimary,
      surfaceTintColor: Colors.transparent,
      elevation: 0,
      centerTitle: false,
      titleTextStyle: buildTravelMateTextTheme().headlineSmall,
    ),
    cardTheme: CardThemeData(
      color: AppColors.surface,
      elevation: 0,
      margin: EdgeInsets.zero,
      shape: RoundedRectangleBorder(
        side: const BorderSide(color: AppColors.divider),
        borderRadius: AppRadii.card,
      ),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: AppColors.surface,
      contentPadding: const EdgeInsets.symmetric(
        horizontal: AppSpacing.md,
        vertical: AppSpacing.md,
      ),
      hintStyle: const TextStyle(color: AppColors.textSecondary),
      errorStyle: const TextStyle(color: AppColors.error),
      border: OutlineInputBorder(
        borderRadius: AppRadii.control,
        borderSide: const BorderSide(color: AppColors.divider),
      ),
      enabledBorder: OutlineInputBorder(
        borderRadius: AppRadii.control,
        borderSide: const BorderSide(color: AppColors.divider),
      ),
      focusedBorder: OutlineInputBorder(
        borderRadius: AppRadii.control,
        borderSide: const BorderSide(color: AppColors.primary, width: 1.6),
      ),
      errorBorder: OutlineInputBorder(
        borderRadius: AppRadii.control,
        borderSide: const BorderSide(color: AppColors.error),
      ),
      focusedErrorBorder: OutlineInputBorder(
        borderRadius: AppRadii.control,
        borderSide: const BorderSide(color: AppColors.error, width: 1.6),
      ),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        minimumSize: const Size(0, AppSizes.minimumTapTarget),
        backgroundColor: AppColors.primary,
        foregroundColor: Colors.white,
        disabledBackgroundColor: AppColors.divider,
        disabledForegroundColor: AppColors.textSecondary,
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
        shape: controlShape,
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        minimumSize: const Size(0, AppSizes.minimumTapTarget),
        foregroundColor: AppColors.primaryStrong,
        side: const BorderSide(color: AppColors.primary),
        padding: const EdgeInsets.symmetric(
            horizontal: AppSpacing.lg, vertical: AppSpacing.sm),
        shape: controlShape,
      ),
    ),
    textButtonTheme: TextButtonThemeData(
      style: TextButton.styleFrom(
        minimumSize:
            const Size(AppSizes.minimumTapTarget, AppSizes.minimumTapTarget),
        foregroundColor: AppColors.primaryStrong,
        padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
        shape: controlShape,
      ),
    ),
    iconButtonTheme: IconButtonThemeData(
      style: IconButton.styleFrom(
        minimumSize:
            const Size(AppSizes.minimumTapTarget, AppSizes.minimumTapTarget),
        foregroundColor: AppColors.textPrimary,
      ),
    ),
    chipTheme: ChipThemeData(
      backgroundColor: AppColors.surfaceElevated,
      selectedColor: AppColors.primarySoft,
      disabledColor: AppColors.divider,
      side: const BorderSide(color: AppColors.divider),
      shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppRadii.pill)),
      labelStyle: buildTravelMateTextTheme().labelMedium,
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
    ),
    snackBarTheme: SnackBarThemeData(
      behavior: SnackBarBehavior.floating,
      backgroundColor: AppColors.textPrimary,
      contentTextStyle:
          buildTravelMateTextTheme().bodyMedium?.copyWith(color: Colors.white),
      shape: RoundedRectangleBorder(borderRadius: AppRadii.control),
    ),
    dialogTheme: DialogThemeData(
      backgroundColor: AppColors.surface,
      surfaceTintColor: Colors.transparent,
      shape: RoundedRectangleBorder(borderRadius: AppRadii.card),
    ),
    progressIndicatorTheme:
        const ProgressIndicatorThemeData(color: AppColors.primary),
    navigationBarTheme: NavigationBarThemeData(
      height: AppSizes.navigationBar,
      backgroundColor: AppColors.surface,
      indicatorColor: InkWashColors.cream,
      surfaceTintColor: Colors.transparent,
      labelTextStyle:
          WidgetStatePropertyAll(buildTravelMateTextTheme().labelMedium),
    ),
  );
}
