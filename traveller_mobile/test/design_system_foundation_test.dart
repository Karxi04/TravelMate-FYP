import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/core/navigation/app_shell_navigation.dart';
import 'package:travelmate_traveller/theme/app_theme.dart';
import 'package:travelmate_traveller/widgets/travel_widgets.dart';

void main() {
  test('Ink Wash theme exposes the production foundation roles', () {
    final theme = buildInkWashTheme();

    expect(theme.scaffoldBackgroundColor, AppColors.background);
    expect(theme.colorScheme.primary, AppColors.primary);
    expect(theme.colorScheme.error, AppColors.error);
    expect(theme.textTheme.headlineLarge?.fontSize, 28);
    expect(theme.textTheme.bodyMedium?.fontSize, 14);
    expect(
      theme.filledButtonTheme.style?.minimumSize?.resolve(<WidgetState>{}),
      const Size(0, AppSizes.minimumTapTarget),
    );
  });

  testWidgets('shared recommendation source badges identify provenance',
      (tester) async {
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: const Scaffold(
          body: Column(
            children: [
              SourceFallbackBadge(source: 'provider'),
              SourceFallbackBadge(source: 'cache'),
              SourceFallbackBadge(source: 'fallback'),
            ],
          ),
        ),
      ),
    );

    expect(find.text('Live source'), findsOneWidget);
    expect(find.text('Cached source'), findsOneWidget);
    expect(find.text('Fallback source'), findsOneWidget);
  });

  testWidgets('primary loading action cannot submit twice', (tester) async {
    var submissions = 0;
    await tester.pumpWidget(
      MaterialApp(
        theme: buildInkWashTheme(),
        home: Scaffold(
          body: PrimaryButton(
            label: 'Build itinerary',
            loading: true,
            onPressed: () => submissions += 1,
          ),
        ),
      ),
    );

    await tester.tap(find.byType(PrimaryButton));
    expect(submissions, 0);
    expect(find.byType(CircularProgressIndicator), findsOneWidget);
  });

  testWidgets('features can select the root Trips tab without pushing a route',
      (tester) async {
    AppShellTab? selected;

    await tester.pumpWidget(
      MaterialApp(
        home: AppShellNavigation(
          selectedTab: AppShellTab.explore,
          onSelect: (tab) => selected = tab,
          child: Builder(
            builder: (context) => TextButton(
              onPressed: () =>
                  AppShellNavigation.select(context, AppShellTab.trips),
              child: const Text('Go to Trips'),
            ),
          ),
        ),
      ),
    );

    await tester.tap(find.text('Go to Trips'));
    expect(selected, AppShellTab.trips);
    expect(find.byType(Navigator), findsOneWidget);
  });
}
