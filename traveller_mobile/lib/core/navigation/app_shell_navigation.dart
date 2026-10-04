import 'package:flutter/widgets.dart';

enum AppShellTab { home, explore, trips, assistant, profile }

/// Lets features select an existing root tab without pushing a second copy of
/// that tab onto the navigation stack.
class AppShellNavigation extends InheritedWidget {
  final AppShellTab selectedTab;
  final ValueChanged<AppShellTab> onSelect;

  const AppShellNavigation({
    super.key,
    required this.selectedTab,
    required this.onSelect,
    required super.child,
  });

  static AppShellNavigation? maybeOf(BuildContext context) {
    return context.dependOnInheritedWidgetOfExactType<AppShellNavigation>();
  }

  static bool select(BuildContext context, AppShellTab tab) {
    final navigation = maybeOf(context);
    if (navigation == null) return false;
    navigation.onSelect(tab);
    return true;
  }

  @override
  bool updateShouldNotify(AppShellNavigation oldWidget) {
    return selectedTab != oldWidget.selectedTab ||
        onSelect != oldWidget.onSelect;
  }
}
