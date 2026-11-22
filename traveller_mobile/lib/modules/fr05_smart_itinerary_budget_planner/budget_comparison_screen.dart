import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import 'alternative_screen.dart';
import 'budget_breakdown.dart';
import 'models/budget_model.dart';

class BudgetComparisonScreen extends StatefulWidget {
  final BudgetModel budget;
  final double userBudget;
  final String? tripId;
  final ApiService? api;
  final ValueChanged<Map<String, dynamic>>? onApplied;
  final ValueChanged<Map<String, dynamic>>? onBudgetLoaded;
  final bool refreshOnOpen;

  const BudgetComparisonScreen({
    super.key,
    required this.budget,
    required this.userBudget,
    this.tripId,
    this.api,
    this.onApplied,
    this.onBudgetLoaded,
    this.refreshOnOpen = false,
  });

  @override
  State<BudgetComparisonScreen> createState() => _BudgetComparisonScreenState();
}

class _BudgetComparisonScreenState extends State<BudgetComparisonScreen> {
  BudgetModel? _appliedBudget;
  bool refreshing = false;
  String? error;
  int requestVersion = 0;

  BudgetModel get budget => _appliedBudget ?? widget.budget;
  double get limit => _appliedBudget?.budgetLimit ?? widget.userBudget;

  @override
  void initState() {
    super.initState();
    if (widget.refreshOnOpen) refresh();
  }

  Future<void> refresh() async {
    if (refreshing || widget.api == null || widget.tripId == null) return;
    final version = ++requestVersion;
    setState(() {
      refreshing = true;
      error = null;
    });
    try {
      final result =
          await widget.api!.get('/api/fr5/itineraries/${widget.tripId}/budget');
      if (!mounted || version != requestVersion) return;
      if (result is! Map || result['ok'] == false || result['budget'] is! Map)
        throw StateError('Invalid budget response');
      final json = Map<String, dynamic>.from(result['budget']);
      setState(() =>
          _appliedBudget = BudgetModel.fromJson(json, fallbackLimit: limit));
      widget.onBudgetLoaded?.call(json);
    } catch (e) {
      if (mounted && version == requestVersion)
        setState(() => error = e is StateError
            ? 'Budget details are unavailable. Please try again.'
            : userFacingApiError(e));
    } finally {
      if (mounted && version == requestVersion)
        setState(() => refreshing = false);
    }
  }

  @override
  void didUpdateWidget(covariant BudgetComparisonScreen oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (widget.budget != oldWidget.budget ||
        widget.tripId != oldWidget.tripId) {
      _appliedBudget = null;
      requestVersion++;
      refreshing = false;
      if (widget.refreshOnOpen) refresh();
    }
  }

  @override
  Widget build(BuildContext context) {
    final canBrowse = budget.isOverBudget(limit);

    return Scaffold(
        appBar: AppBar(
          title: const Text("Budget Comparison"),
          actions: [
            if (widget.api != null && widget.tripId != null)
              IconButton(
                  tooltip: 'Refresh budget',
                  onPressed: refreshing ? null : refresh,
                  icon: const Icon(Icons.refresh))
          ],
        ),
        body: ListView(padding: const EdgeInsets.all(AppSpacing.lg), children: [
          if (refreshing) ...[
            const LinearProgressIndicator(),
            const Text('Refreshing budget…'),
            const SizedBox(height: 12)
          ],
          if (error != null) ...[
            Text(error!),
            TextButton(
                onPressed: refreshing ? null : refresh,
                child: const Text('Retry budget'))
          ],
          InkCard(child: BudgetBreakdown(budget: budget, limit: limit)),
          if (canBrowse)
            ElevatedButton(
              child: Text(budget.isOverBudget(limit)
                  ? 'Review budget options'
                  : 'View Lower-Cost Alternatives'),
              onPressed: refreshing
                  ? null
                  : () {
                      Navigator.push(
                          context,
                          MaterialPageRoute(
                              builder: (context) => AlternativeScreen(
                                    budget: budget,
                                    userBudget: limit,
                                    tripId: widget.tripId,
                                    api: widget.api,
                                    onApplied: (trip) {
                                      final estimate = trip['budgetEstimate'];
                                      if (mounted && estimate is Map) {
                                        setState(() {
                                          requestVersion++;
                                          refreshing = false;
                                          _appliedBudget = BudgetModel.fromJson(
                                            Map<String, dynamic>.from(estimate),
                                            fallbackLimit: widget.userBudget,
                                          );
                                        });
                                      }
                                      widget.onApplied?.call(trip);
                                    },
                                  )));
                    },
            )
        ]));
  }
}
