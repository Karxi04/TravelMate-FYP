import 'dart:async';
import 'package:flutter/foundation.dart';
import '../../core/utils/destination_utils.dart';
import '../../services/api_service.dart';

/// The existing favourites API remains authoritative; the signal carries no user data.
class FavouritesController extends ChangeNotifier {
  static final _changes = ValueNotifier(0);
  final ApiService api;
  List<Map<String, dynamic>> items = [];
  final Set<String> busyIds = {};
  bool loaded = false;
  String? error;
  bool _disposed = false;
  int _version = 0;

  FavouritesController(this.api) {
    _changes.addListener(_refresh);
    unawaited(load());
  }

  void _refresh() => unawaited(load());
  bool contains(String id) => items.any((e) => DestinationUtils.resolveId(e) == id);

  Future<void> load() async {
    final version = ++_version;
    try {
      final data = await api.get('/api/fr3/favourites');
      if (_disposed || version != _version) return;
      items = (data['items'] as List? ?? []).whereType<Map>()
          .map((e) => Map<String, dynamic>.from(e)).toList();
      loaded = true;
      error = null;
    } catch (_) {
      if (_disposed || version != _version) return;
      error = 'We could not refresh your saved places. Please retry.';
    }
    if (!_disposed && version == _version) notifyListeners();
  }

  Future<void> toggle(Map<String, dynamic> destination) async {
    final id = DestinationUtils.resolveId(destination);
    if (id.isEmpty || busyIds.contains(id)) return;
    if (!loaded || error != null) {
      throw const ApiException('Refresh your saved places before changing favourites.', 409, {});
    }
    busyIds.add(id);
    notifyListeners();
    try {
      final existing = items.where((e) => DestinationUtils.resolveId(e) == id).toList();
      if (existing.isEmpty) {
        await api.post('/api/fr3/favourites', {...destination, 'destinationId': id});
      } else {
        for (final record in existing) {
          await api.delete('/api/fr3/favourites/${Uri.encodeComponent(record['id'].toString())}');
        }
      }
    } finally {
      // Re-read even after an ambiguous failure; never claim an optimistic success.
      _changes.value++;
      await load();
      busyIds.remove(id);
      if (!_disposed) notifyListeners();
    }
  }

  @override
  void dispose() {
    _disposed = true;
    _version++;
    _changes.removeListener(_refresh);
    super.dispose();
  }
}
