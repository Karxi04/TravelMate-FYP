import '../../services/api_service.dart';
import 'models/packing_models.dart';

class PackingService {
  final ApiService api;

  PackingService({ApiService? api}) : api = api ?? ApiService();

  String _checklistPath(String tripId) =>
      '/api/fr5/itineraries/$tripId/packing-checklist';

  Future<PackingChecklistResponse> getChecklist(String tripId) async {
    final raw = await api.get(_checklistPath(tripId));
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> generateChecklist(String tripId) async {
    final raw = await api.post(
      _checklistPath(tripId),
      {'action': 'generate'},
    );
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> refreshChecklist(
    String tripId, {
    required int expectedRevision,
  }) async {
    final raw = await api.post(
      _checklistPath(tripId),
      {
        'action': 'refresh',
        'expectedRevision': expectedRevision,
      },
    );
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> updateItem(
    String tripId, {
    required int expectedRevision,
    required String itemId,
    String? name,
    String? category,
    int? quantity,
    bool? isPacked,
  }) async {
    final payload = <String, dynamic>{
      'action': 'update',
      'expectedRevision': expectedRevision,
      'itemId': itemId,
      if (name != null) 'name': name,
      if (category != null) 'category': category,
      if (quantity != null) 'quantity': quantity,
      if (isPacked != null) 'isPacked': isPacked,
    };
    final raw = await api.patch(_checklistPath(tripId), payload);
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> addItem(
    String tripId, {
    required int expectedRevision,
    required String itemId,
    required String name,
    required String category,
    int quantity = 1,
  }) async {
    final payload = <String, dynamic>{
      'action': 'add',
      'expectedRevision': expectedRevision,
      'itemId': itemId,
      'name': name,
      'category': category,
      'quantity': quantity,
    };
    final raw = await api.patch(_checklistPath(tripId), payload);
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> removeItem(
    String tripId, {
    required int expectedRevision,
    required String itemId,
  }) async {
    final payload = <String, dynamic>{
      'action': 'remove',
      'expectedRevision': expectedRevision,
      'itemId': itemId,
    };
    final raw = await api.patch(_checklistPath(tripId), payload);
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }

  Future<PackingChecklistResponse> restoreItem(
    String tripId, {
    required int expectedRevision,
    required String itemId,
  }) async {
    final payload = <String, dynamic>{
      'action': 'restore',
      'expectedRevision': expectedRevision,
      'itemId': itemId,
    };
    final raw = await api.patch(_checklistPath(tripId), payload);
    if (raw is Map) {
      return PackingChecklistResponse.fromJson(Map<String, dynamic>.from(raw));
    }
    throw const ApiException('Invalid packing response format', 500, {});
  }
}
