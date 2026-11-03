import 'dart:math' as math;
import 'package:flutter/material.dart';

import '../../services/api_service.dart';
import '../../theme/app_theme.dart';
import '../../widgets/ink_card.dart';
import '../../widgets/travel_widgets.dart';
import 'models/packing_models.dart';
import 'packing_service.dart';

class PackingChecklistScreen extends StatefulWidget {
  final String tripId;
  final String? tripTitle;
  final String? destination;
  final int? durationDays;
  final ApiService? api;

  const PackingChecklistScreen({
    super.key,
    required this.tripId,
    this.tripTitle,
    this.destination,
    this.durationDays,
    this.api,
  });

  @override
  State<PackingChecklistScreen> createState() => _PackingChecklistScreenState();
}

class _PackingChecklistScreenState extends State<PackingChecklistScreen> {
  late final ApiService _api;
  late final PackingService _service;

  bool _loading = true;
  bool _mutating = false;
  String? _error;
  int? _statusCode;
  PackingChecklistResponse? _response;

  @override
  void initState() {
    super.initState();
    _api = widget.api ?? ApiService();
    _service = PackingService(api: _api);
    _loadChecklist();
  }

  bool get _isStandalone => _api.isStandalone;

  Future<void> _loadChecklist({bool showLoading = true}) async {
    if (_isStandalone) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'Smart Packing Checklist requires an active TravelMate backend connection. Standalone mode cannot persist checklists.';
          _statusCode = 503;
        });
      }
      return;
    }

    if (showLoading && mounted) {
      setState(() {
        _loading = true;
        _error = null;
        _statusCode = null;
      });
    }

    try {
      final res = await _service.getChecklist(widget.tripId);
      if (mounted) {
        setState(() {
          _response = res;
          _loading = false;
          _error = null;
          _statusCode = null;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() {
          _loading = false;
          _statusCode = e.statusCode;
          if (e.statusCode == 404) {
            _error = 'Trip not found or no longer accessible.';
          } else if (e.statusCode == 401) {
            _error = 'Please log in to view your packing checklist.';
          } else if (e.statusCode == 403) {
            _error = 'You do not have permission to view this checklist.';
          } else {
            _error = e.message;
          }
        });
      }
    } catch (_) {
      if (mounted) {
        setState(() {
          _loading = false;
          _error = 'We couldn\'t load your packing checklist. Please check your connection and try again.';
          _statusCode = 500;
        });
      }
    }
  }

  Future<void> _generateChecklist() async {
    if (_isStandalone || _mutating) return;
    setState(() => _mutating = true);
    try {
      final res = await _service.generateChecklist(widget.tripId);
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Packing suggestions generated.')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Failed to generate checklist. Please try again.');
      }
    }
  }

  Future<void> _refreshChecklist() async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;
    setState(() => _mutating = true);
    try {
      final res = await _service.refreshChecklist(
        widget.tripId,
        expectedRevision: checklist.revision,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        final changes = res.changes;
        String msg = 'Packing suggestions updated.';
        if (changes != null) {
          if (changes.added > 0 && changes.inactive > 0) {
            msg = 'Added ${changes.added} new item(s), ${changes.inactive} item(s) no longer needed.';
          } else if (changes.added > 0) {
            msg = 'Added ${changes.added} new suggestion(s).';
          } else if (changes.inactive > 0) {
            msg = '${changes.inactive} suggestion(s) marked inactive for changed itinerary.';
          }
        }
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Failed to refresh suggestions. Please try again.');
      }
    }
  }

  Future<void> _togglePacked(PackingItem item, bool isPacked) async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;

    setState(() => _mutating = true);
    try {
      final res = await _service.updateItem(
        widget.tripId,
        expectedRevision: checklist.revision,
        itemId: item.itemId,
        isPacked: isPacked,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Couldn\'t save packing status. Please try again.');
      }
    }
  }

  Future<void> _addCustomItem(String name, String category, int quantity) async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;

    final customId = 'custom_${DateTime.now().millisecondsSinceEpoch}_${math.Random().nextInt(9999)}';
    setState(() => _mutating = true);
    try {
      final res = await _service.addItem(
        widget.tripId,
        expectedRevision: checklist.revision,
        itemId: customId,
        name: name.trim(),
        category: category,
        quantity: quantity,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Added "${name.trim()}".')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Couldn\'t add item. Please try again.');
      }
    }
  }

  Future<void> _updateItemDetails(PackingItem item, {String? name, String? category, int? quantity}) async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;

    setState(() => _mutating = true);
    try {
      final res = await _service.updateItem(
        widget.tripId,
        expectedRevision: checklist.revision,
        itemId: item.itemId,
        name: name,
        category: category,
        quantity: quantity,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('Item updated.')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Couldn\'t update item. Please try again.');
      }
    }
  }

  Future<void> _removeItem(PackingItem item) async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;

    setState(() => _mutating = true);
    try {
      final res = await _service.removeItem(
        widget.tripId,
        expectedRevision: checklist.revision,
        itemId: item.itemId,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text(item.isCustom ? 'Item removed.' : 'Suggestion hidden from checklist.'),
          ),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Couldn\'t remove item. Please try again.');
      }
    }
  }

  Future<void> _restoreItem(PackingItem item) async {
    final checklist = _response?.checklist;
    if (_isStandalone || _mutating || checklist == null) return;

    setState(() => _mutating = true);
    try {
      final res = await _service.restoreItem(
        widget.tripId,
        expectedRevision: checklist.revision,
        itemId: item.itemId,
      );
      if (mounted) {
        setState(() {
          _response = res;
          _mutating = false;
        });
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(content: Text('Restored "${item.name}".')),
        );
      }
    } on ApiException catch (e) {
      if (mounted) {
        setState(() => _mutating = false);
        _handleApiException(e);
      }
    } catch (_) {
      if (mounted) {
        setState(() => _mutating = false);
        _showErrorSnackBar('Couldn\'t restore item. Please try again.');
      }
    }
  }

  void _handleApiException(ApiException e) {
    if (e.statusCode == 409) {
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(
          content: Text('Checklist changed on server. Reloading current state…'),
          duration: Duration(seconds: 3),
        ),
      );
      _loadChecklist(showLoading: false);
    } else if (e.statusCode == 503) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.message),
          action: SnackBarAction(
            label: 'Retry',
            onPressed: () => _loadChecklist(showLoading: false),
          ),
        ),
      );
      _loadChecklist(showLoading: false);
    } else {
      _showErrorSnackBar(e.message);
    }
  }

  void _showErrorSnackBar(String message) {
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(message),
        backgroundColor: AppColors.error,
      ),
    );
  }

  void _openAddItemSheet() {
    if (_isStandalone || _mutating) return;
    final categories = _response?.categories ?? PackingChecklistResponse.defaultCategories;
    String selectedCat = categories.isNotEmpty ? categories.first.id : 'miscellaneous';
    int quantity = 1;
    final nameController = TextEditingController();
    final formKey = GlobalKey<FormState>();

    showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: Colors.transparent,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setSheetState) {
            return Padding(
              padding: EdgeInsets.only(
                bottom: MediaQuery.of(ctx).viewInsets.bottom,
              ),
              child: Container(
                decoration: const BoxDecoration(
                  color: AppColors.surface,
                  borderRadius: BorderRadius.vertical(top: Radius.circular(20)),
                ),
                padding: const EdgeInsets.all(AppSpacing.md),
                child: Form(
                  key: formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        mainAxisAlignment: MainAxisAlignment.spaceBetween,
                        children: [
                          Text('Add Custom Item', style: Theme.of(ctx).textTheme.titleMedium),
                          IconButton(
                            icon: const Icon(Icons.close_rounded),
                            onPressed: () => Navigator.pop(ctx),
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      TextFormField(
                        controller: nameController,
                        autofocus: true,
                        decoration: const InputDecoration(
                          labelText: 'Item name *',
                          hintText: 'e.g. Extra power bank, Sunhat',
                        ),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) return 'Enter an item name';
                          if (val.trim().length > 100) return 'Name must be 100 characters or less';
                          if (val.contains('<') || val.contains('>')) return 'HTML markup is not allowed';
                          return null;
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      DropdownButtonFormField<String>(
                        initialValue: selectedCat,
                        decoration: const InputDecoration(labelText: 'Category'),
                        items: categories.map((cat) {
                          return DropdownMenuItem(
                            value: cat.id,
                            child: Text(cat.name),
                          );
                        }).toList(),
                        onChanged: (val) {
                          if (val != null) setSheetState(() => selectedCat = val);
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      Row(
                        children: [
                          const Text('Quantity: ', style: TextStyle(fontWeight: FontWeight.w600)),
                          IconButton(
                            icon: const Icon(Icons.remove_circle_outline),
                            onPressed: quantity > 1 ? () => setSheetState(() => quantity--) : null,
                          ),
                          Text('$quantity', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                          IconButton(
                            icon: const Icon(Icons.add_circle_outline),
                            onPressed: quantity < 30 ? () => setSheetState(() => quantity++) : null,
                          ),
                        ],
                      ),
                      const SizedBox(height: AppSpacing.md),
                      SizedBox(
                        width: double.infinity,
                        child: PrimaryButton(
                          label: 'Add to Checklist',
                          onPressed: () {
                            if (formKey.currentState?.validate() ?? false) {
                              final name = nameController.text;
                              Navigator.pop(ctx);
                              _addCustomItem(name, selectedCat, quantity);
                            }
                          },
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            );
          },
        );
      },
    );
  }

  void _openEditItemDialog(PackingItem item) {
    if (_isStandalone || _mutating) return;
    final categories = _response?.categories ?? PackingChecklistResponse.defaultCategories;
    String selectedCat = item.category;
    int quantity = item.quantity;
    final nameController = TextEditingController(text: item.name);
    final formKey = GlobalKey<FormState>();

    showDialog(
      context: context,
      builder: (ctx) {
        return StatefulBuilder(
          builder: (ctx, setDialogState) {
            return AlertDialog(
              title: Text(item.isCustom ? 'Edit Custom Item' : 'Edit Item Quantity'),
              content: Form(
                key: formKey,
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    if (item.isCustom) ...[
                      TextFormField(
                        controller: nameController,
                        decoration: const InputDecoration(labelText: 'Item name'),
                        validator: (val) {
                          if (val == null || val.trim().isEmpty) return 'Enter an item name';
                          if (val.trim().length > 100) return 'Name must be 100 characters or less';
                          if (val.contains('<') || val.contains('>')) return 'HTML markup is not allowed';
                          return null;
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                      DropdownButtonFormField<String>(
                        initialValue: categories.any((c) => c.id == selectedCat) ? selectedCat : categories.first.id,
                        decoration: const InputDecoration(labelText: 'Category'),
                        items: categories.map((cat) {
                          return DropdownMenuItem(value: cat.id, child: Text(cat.name));
                        }).toList(),
                        onChanged: (val) {
                          if (val != null) setDialogState(() => selectedCat = val);
                        },
                      ),
                      const SizedBox(height: AppSpacing.sm),
                    ],
                    Row(
                      children: [
                        const Text('Quantity: ', style: TextStyle(fontWeight: FontWeight.w600)),
                        IconButton(
                          icon: const Icon(Icons.remove_circle_outline),
                          onPressed: quantity > 1 ? () => setDialogState(() => quantity--) : null,
                        ),
                        Text('$quantity', style: const TextStyle(fontWeight: FontWeight.bold, fontSize: 16)),
                        IconButton(
                          icon: const Icon(Icons.add_circle_outline),
                          onPressed: quantity < 30 ? () => setDialogState(() => quantity++) : null,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              actions: [
                TextButton(
                  onPressed: () => Navigator.pop(ctx),
                  child: const Text('Cancel'),
                ),
                PrimaryButton(
                  label: 'Save',
                  onPressed: () {
                    if (formKey.currentState?.validate() ?? true) {
                      Navigator.pop(ctx);
                      _updateItemDetails(
                        item,
                        name: item.isCustom ? nameController.text.trim() : null,
                        category: item.isCustom ? selectedCat : null,
                        quantity: quantity,
                      );
                    }
                  },
                ),
              ],
            );
          },
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final title = widget.tripTitle ?? _response?.checklist?.tripContext['title']?.toString() ?? 'Trip';

    return TravelMatePageScaffold(
      appBar: AppBar(
        title: const Text('Packing Checklist'),
        actions: [
          if (!_isStandalone && _response != null && !_response!.isNotGenerated)
            IconButton(
              icon: const Icon(Icons.refresh_rounded),
              tooltip: 'Refresh suggestions',
              onPressed: _mutating ? null : _refreshChecklist,
            ),
        ],
      ),
      floatingActionButton: (!_isStandalone && _response != null && !_response!.isNotGenerated)
          ? FloatingActionButton.extended(
              onPressed: _mutating ? null : _openAddItemSheet,
              icon: const Icon(Icons.add_rounded),
              label: const Text('Add Item'),
            )
          : null,
      body: _buildBody(title),
    );
  }

  Widget _buildBody(String title) {
    if (_loading) {
      return const AppLoadingState(message: 'Loading packing checklist…');
    }

    if (_statusCode == 404) {
      return Center(
        child: InkCard(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.luggage_outlined, size: 48, color: AppColors.textSecondary),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'Trip Unavailable',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              Text(
                _error ?? 'Trip not found or no longer accessible.',
                textAlign: TextAlign.center,
                style: const TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.md),
              SecondaryButton(
                label: 'Go back',
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
      );
    }

    if (_isStandalone) {
      return Center(
        child: InkCard(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_rounded, size: 48, color: AppColors.textSecondary),
              const SizedBox(height: AppSpacing.sm),
              Text(
                'Connection Required',
                style: Theme.of(context).textTheme.titleMedium,
              ),
              const SizedBox(height: AppSpacing.xs),
              const Text(
                'Smart Packing Checklist requires an active TravelMate backend connection. Standalone mode cannot persist checklists.',
                textAlign: TextAlign.center,
                style: TextStyle(color: AppColors.textSecondary),
              ),
              const SizedBox(height: AppSpacing.md),
              SecondaryButton(
                label: 'Go back',
                onPressed: () => Navigator.pop(context),
              ),
            ],
          ),
        ),
      );
    }

    if (_error != null && _response == null) {
      return AppErrorState(
        title: 'Checklist unavailable',
        message: _error!,
        retryLabel: 'Try again',
        onRetry: _loadChecklist,
      );
    }

    final resp = _response;
    if (resp == null || resp.isNotGenerated) {
      return _buildNotGeneratedState(title);
    }

    final checklist = resp.checklist!;
    final progress = resp.progress;
    final activeItems = checklist.activeItems;
    final suppressedItems = checklist.suppressedItems;

    return RefreshIndicator(
      onRefresh: () => _loadChecklist(showLoading: false),
      child: ListView(
        physics: const AlwaysScrollableScrollPhysics(),
        children: [
          _buildHeaderCard(title, checklist, progress),
          const SizedBox(height: AppSpacing.sm),
          if (resp.weatherContext.isUnavailable)
            _buildWeatherNotice(resp.weatherContext),
          if (resp.needsRefresh)
            _buildRefreshBanner(),
          if (activeItems.isEmpty)
            _buildEmptyState()
          else
            ..._buildCategorySections(resp.categories, checklist),
          if (suppressedItems.isNotEmpty)
            _buildSuppressedSection(suppressedItems),
          const SizedBox(height: 80), // Padding for FAB
        ],
      ),
    );
  }

  Widget _buildNotGeneratedState(String title) {
    return Center(
      child: InkCard(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Icon(Icons.checklist_rounded, size: 56, color: AppColors.primary),
            const SizedBox(height: AppSpacing.md),
            Text(
              'Packing Checklist for $title',
              textAlign: TextAlign.center,
              style: Theme.of(context).textTheme.titleLarge,
            ),
            const SizedBox(height: AppSpacing.xs),
            const Text(
              'Generate a personalized packing checklist tailored to your destination, activities, and trip duration.',
              textAlign: TextAlign.center,
              style: TextStyle(color: AppColors.textSecondary),
            ),
            const SizedBox(height: AppSpacing.lg),
            PrimaryButton(
              label: 'Generate Checklist',
              icon: Icons.auto_awesome_rounded,
              loading: _mutating,
              onPressed: _mutating ? null : _generateChecklist,
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildHeaderCard(String title, PackingChecklist checklist, PackingProgress progress) {
    final dest = widget.destination ?? checklist.tripContext['destination']?.toString() ?? '';
    final duration = widget.durationDays ?? checklist.tripContext['durationDays'] as int?;
    final durationText = duration != null ? '$duration ${duration == 1 ? 'Day' : 'Days'}' : '';

    return InkCard(
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(title, style: Theme.of(context).textTheme.titleLarge),
                    if (dest.isNotEmpty || durationText.isNotEmpty) ...[
                      const SizedBox(height: 2),
                      Text(
                        [dest, durationText].where((s) => s.isNotEmpty).join(' • '),
                        style: const TextStyle(
                          color: AppColors.textSecondary,
                          fontWeight: FontWeight.w500,
                        ),
                      ),
                    ],
                  ],
                ),
              ),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                decoration: BoxDecoration(
                  color: AppColors.primary.withAlpha(25),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Text(
                  'Rev ${checklist.revision}',
                  style: const TextStyle(
                    color: AppColors.primary,
                    fontWeight: FontWeight.bold,
                    fontSize: 12,
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.md),
          Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text(
                'Packing Progress: ${progress.packedItems} of ${progress.totalItems} Items Packed',
                style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 13),
              ),
              Text(
                '${progress.completionPercentage.toStringAsFixed(1)}%',
                style: const TextStyle(
                  fontWeight: FontWeight.bold,
                  color: AppColors.primary,
                  fontSize: 14,
                ),
              ),
            ],
          ),
          const SizedBox(height: AppSpacing.xs),
          ClipRRect(
            borderRadius: BorderRadius.circular(8),
            child: LinearProgressIndicator(
              value: progress.totalItems > 0 ? (progress.completionPercentage / 100.0).clamp(0.0, 1.0) : 0.0,
              minHeight: 8,
              backgroundColor: AppColors.divider,
              valueColor: const AlwaysStoppedAnimation<Color>(AppColors.primary),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildWeatherNotice(PackingWeatherContext weatherContext) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
        decoration: BoxDecoration(
          color: Colors.amber.withAlpha(25),
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: Colors.amber.withAlpha(80)),
        ),
        child: Row(
          children: [
            const Icon(Icons.cloud_outlined, size: 18, color: Colors.orange),
            const SizedBox(width: 8),
            Expanded(
              child: Text(
                weatherContext.message ?? 'Current trip weather is unavailable; weather items are general precautions.',
                style: const TextStyle(fontSize: 12, color: Colors.black87),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildRefreshBanner() {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: Container(
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: AppColors.primary.withAlpha(20),
          borderRadius: BorderRadius.circular(10),
          border: Border.all(color: AppColors.primary.withAlpha(80)),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: const [
                Icon(Icons.info_outline_rounded, size: 18, color: AppColors.primary),
                SizedBox(width: 6),
                Text(
                  'Itinerary Changed',
                  style: TextStyle(fontWeight: FontWeight.bold, color: AppColors.primary),
                ),
              ],
            ),
            const SizedBox(height: 4),
            const Text(
              'Your itinerary has changed. Refresh packing suggestions to include relevant items while keeping your personal changes.',
              style: TextStyle(fontSize: 12.5),
            ),
            const SizedBox(height: 8),
            Align(
              alignment: Alignment.centerRight,
              child: SecondaryButton(
                label: 'Refresh Suggestions',
                icon: Icons.refresh_rounded,
                onPressed: _mutating ? null : _refreshChecklist,
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildEmptyState() {
    return InkCard(
      child: Column(
        children: [
          const Icon(Icons.inbox_outlined, size: 40, color: AppColors.textSecondary),
          const SizedBox(height: AppSpacing.sm),
          const Text(
            'No items in your packing checklist.',
            style: TextStyle(fontWeight: FontWeight.w600),
          ),
          const SizedBox(height: AppSpacing.xs),
          const Text(
            'Add custom items below or tap Refresh to reload suggestions.',
            textAlign: TextAlign.center,
            style: TextStyle(color: AppColors.textSecondary, fontSize: 13),
          ),
          const SizedBox(height: AppSpacing.md),
          SecondaryButton(
            label: 'Add an item',
            icon: Icons.add_rounded,
            onPressed: _openAddItemSheet,
          ),
        ],
      ),
    );
  }

  List<Widget> _buildCategorySections(List<PackingCategory> categories, PackingChecklist checklist) {
    final widgets = <Widget>[];

    for (final cat in categories) {
      final items = checklist.itemsForCategory(cat.id);
      if (items.isEmpty) continue;

      widgets.add(
        Padding(
          padding: const EdgeInsets.only(bottom: AppSpacing.sm),
          child: InkCard(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    Text(
                      cat.name,
                      style: Theme.of(context).textTheme.titleMedium?.copyWith(
                            fontWeight: FontWeight.bold,
                          ),
                    ),
                    Text(
                      '${items.where((i) => i.isPacked).length}/${items.length}',
                      style: const TextStyle(
                        fontWeight: FontWeight.w600,
                        color: AppColors.textSecondary,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
                const Divider(height: 16),
                ...items.map((item) => _buildItemTile(item)),
              ],
            ),
          ),
        ),
      );
    }

    return widgets;
  }

  Widget _buildItemTile(PackingItem item) {
    return Padding(
      padding: const EdgeInsets.symmetric(vertical: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Semantics(
            label: '${item.name}, ${item.isPacked ? "packed" : "unpacked"}',
            child: SizedBox(
              width: 24,
              height: 24,
              child: Checkbox(
                value: item.isPacked,
                activeColor: AppColors.primary,
                onChanged: _mutating
                    ? null
                    : (val) {
                        if (val != null) _togglePacked(item, val);
                      },
              ),
            ),
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        item.name,
                        style: TextStyle(
                          fontSize: 14.5,
                          fontWeight: FontWeight.w500,
                          decoration: item.isPacked ? TextDecoration.lineThrough : null,
                          color: item.isPacked ? AppColors.textSecondary : null,
                        ),
                      ),
                    ),
                    if (item.quantity > 1) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: AppColors.divider.withAlpha(120),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          '×${item.quantity}',
                          style: const TextStyle(fontSize: 11.5, fontWeight: FontWeight.bold),
                        ),
                      ),
                    ],
                    if (item.isCustom) ...[
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                        decoration: BoxDecoration(
                          color: Colors.blue.withAlpha(25),
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: const Text(
                          'Custom',
                          style: TextStyle(fontSize: 10.5, color: Colors.blue, fontWeight: FontWeight.w600),
                        ),
                      ),
                    ],
                  ],
                ),
                if (item.reason != null && item.reason!.isNotEmpty) ...[
                  const SizedBox(height: 2),
                  Text(
                    item.reason!,
                    style: const TextStyle(
                      fontSize: 11.5,
                      color: AppColors.textSecondary,
                    ),
                  ),
                ],
              ],
            ),
          ),
          PopupMenuButton<String>(
            icon: const Icon(Icons.more_vert_rounded, size: 18, color: AppColors.textSecondary),
            padding: EdgeInsets.zero,
            onSelected: (val) {
              if (val == 'edit') {
                _openEditItemDialog(item);
              } else if (val == 'remove') {
                _removeItem(item);
              }
            },
            itemBuilder: (_) => [
              const PopupMenuItem(
                value: 'edit',
                child: Row(
                  children: [
                    Icon(Icons.edit_outlined, size: 16),
                    SizedBox(width: 8),
                    Text('Edit'),
                  ],
                ),
              ),
              PopupMenuItem(
                value: 'remove',
                child: Row(
                  children: [
                    const Icon(Icons.delete_outline, size: 16, color: AppColors.error),
                    const SizedBox(width: 8),
                    Text(
                      item.isCustom ? 'Delete' : 'Hide suggestion',
                      style: const TextStyle(color: AppColors.error),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSuppressedSection(List<PackingItem> suppressedItems) {
    return Padding(
      padding: const EdgeInsets.only(bottom: AppSpacing.sm),
      child: InkCard(
        child: ExpansionTile(
          tilePadding: EdgeInsets.zero,
          title: Text(
            'Hidden suggestions (${suppressedItems.length})',
            style: const TextStyle(
              fontSize: 14,
              fontWeight: FontWeight.w600,
              color: AppColors.textSecondary,
            ),
          ),
          children: suppressedItems.map((item) {
            return Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Expanded(
                    child: Text(
                      item.name,
                      style: const TextStyle(color: AppColors.textSecondary, fontSize: 13.5),
                    ),
                  ),
                  TextButton.icon(
                    icon: const Icon(Icons.undo_rounded, size: 16),
                    label: const Text('Restore'),
                    onPressed: _mutating ? null : () => _restoreItem(item),
                  ),
                ],
              ),
            );
          }).toList(),
        ),
      ),
    );
  }
}
