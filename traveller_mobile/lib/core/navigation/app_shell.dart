import 'package:flutter/material.dart';
import '../home/home_tab.dart';
import '../../modules/fr03_destination_search_information/explore_tab.dart';
import '../../modules/fr05_smart_itinerary_budget_planner/trips_tab.dart';
import '../../modules/fr11_chatbot_travel_assistant/chat_tab.dart';
import '../../modules/fr01_user_management/profile_tab.dart';
import 'app_shell_navigation.dart';

class AppShell extends StatefulWidget {
  const AppShell({super.key});

  @override
  State<AppShell> createState() => _AppShellState();
}

class _AppShellState extends State<AppShell> {
  int index = 0;

  final pages = const [
    HomeTab(),
    ExploreTab(),
    TripsTab(),
    ChatTab(),
    ProfileTab(),
  ];

  @override
  Widget build(BuildContext context) {
    return AppShellNavigation(
      selectedTab: AppShellTab.values[index],
      onSelect: (tab) => setState(() => index = tab.index),
      child: Scaffold(
        body: IndexedStack(index: index, children: pages),
        bottomNavigationBar: NavigationBar(
          selectedIndex: index,
          onDestinationSelected: (value) => setState(() => index = value),
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
    );
  }
}
