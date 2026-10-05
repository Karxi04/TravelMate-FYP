import 'package:flutter/material.dart';
import '../home/home_tab.dart';
import '../../modules/fr03_destination_search_information/explore_tab.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../../modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import '../../modules/fr01_user_management/profile_tab.dart';
import 'app_shell_navigation.dart';

class AppShell extends StatefulWidget {
  final List<Widget>? pages;

  const AppShell({super.key, this.pages});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int index = 0;

  static const _defaultPages = [
    HomeTab(),
    ExploreTab(),
    TripsTab(),
    ChatTab(),
    ProfileTab(),
  ];

  @override
  Widget build(BuildContext context) {
    final pages = widget.pages ?? _defaultPages;
    assert(pages.length == AppShellTab.values.length);

    void select(int value) {
      if (value != index) setState(() => index = value);
    }

    return PopScope(
      canPop: index == AppShellTab.home.index,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop && index != AppShellTab.home.index) {
          select(AppShellTab.home.index);
        }
      },
      child: AppShellNavigation(
        selectedTab: AppShellTab.values[index],
        onSelect: (tab) => select(tab.index),
        child: Scaffold(
          body: IndexedStack(index: index, children: pages),
          bottomNavigationBar: Semantics(
            label: 'Main navigation',
            child: NavigationBar(
              selectedIndex: index,
              onDestinationSelected: select,
              destinations: const [
                NavigationDestination(
                  icon: Icon(Icons.home_outlined),
                  selectedIcon: Icon(Icons.home_rounded),
                  label: 'Home',
                ),
                NavigationDestination(
                  icon: Icon(Icons.travel_explore_outlined),
                  selectedIcon: Icon(Icons.travel_explore_rounded),
                  label: 'Explore',
                ),
                NavigationDestination(
                  icon: Icon(Icons.luggage_outlined),
                  selectedIcon: Icon(Icons.luggage_rounded),
                  label: 'Trips',
                ),
                NavigationDestination(
                  icon: Icon(Icons.auto_awesome_outlined),
                  selectedIcon: Icon(Icons.auto_awesome_rounded),
                  label: 'Assistant',
                ),
                NavigationDestination(
                  icon: Icon(Icons.person_outline_rounded),
                  selectedIcon: Icon(Icons.person_rounded),
                  label: 'Profile',
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
