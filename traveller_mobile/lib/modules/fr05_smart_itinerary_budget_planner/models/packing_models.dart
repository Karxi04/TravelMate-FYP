class PackingCategory {
  final String id;
  final String name;

  const PackingCategory({
    required this.id,
    required this.name,
  });

  factory PackingCategory.fromJson(Map<String, dynamic> json) {
    return PackingCategory(
      id: (json['id'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'id': id,
        'name': name,
      };

  @override
  bool operator ==(Object other) =>
      identical(this, other) ||
      other is PackingCategory &&
          runtimeType == other.runtimeType &&
          id == other.id;

  @override
  int get hashCode => id.hashCode;
}

class PackingItem {
  final String itemId;
  final String name;
  final String category;
  final int quantity;
  final bool isPacked;
  final bool isCustom;
  final String source;
  final String? reason;
  final bool suppressed;
  final bool applicable;
  final List<String> userEditedFields;

  const PackingItem({
    required this.itemId,
    required this.name,
    required this.category,
    this.quantity = 1,
    this.isPacked = false,
    this.isCustom = false,
    this.source = 'general',
    this.reason,
    this.suppressed = false,
    this.applicable = true,
    this.userEditedFields = const [],
  });

  bool get isActive => applicable && !suppressed;
  bool get isSuppressed => suppressed;
  bool get isInactive => !applicable;

  factory PackingItem.fromJson(Map<String, dynamic> json) {
    return PackingItem(
      itemId: (json['itemId'] ?? '').toString(),
      name: (json['name'] ?? '').toString(),
      category: (json['category'] ?? 'miscellaneous').toString(),
      quantity: json['quantity'] is num ? (json['quantity'] as num).toInt() : 1,
      isPacked: json['isPacked'] == true,
      isCustom: json['isCustom'] == true,
      source: (json['source'] ?? 'general').toString(),
      reason: json['reason']?.toString(),
      suppressed: json['suppressed'] == true,
      applicable: json['applicable'] != false,
      userEditedFields: json['userEditedFields'] is List
          ? (json['userEditedFields'] as List).map((e) => e.toString()).toList()
          : const [],
    );
  }

  Map<String, dynamic> toJson() => {
        'itemId': itemId,
        'name': name,
        'category': category,
        'quantity': quantity,
        'isPacked': isPacked,
        'isCustom': isCustom,
        'source': source,
        if (reason != null) 'reason': reason,
        'suppressed': suppressed,
        'applicable': applicable,
        'userEditedFields': userEditedFields,
      };

  PackingItem copyWith({
    String? name,
    String? category,
    int? quantity,
    bool? isPacked,
    bool? isCustom,
    String? source,
    String? reason,
    bool? suppressed,
    bool? applicable,
    List<String>? userEditedFields,
  }) {
    return PackingItem(
      itemId: itemId,
      name: name ?? this.name,
      category: category ?? this.category,
      quantity: quantity ?? this.quantity,
      isPacked: isPacked ?? this.isPacked,
      isCustom: isCustom ?? this.isCustom,
      source: source ?? this.source,
      reason: reason ?? this.reason,
      suppressed: suppressed ?? this.suppressed,
      applicable: applicable ?? this.applicable,
      userEditedFields: userEditedFields ?? this.userEditedFields,
    );
  }
}

class PackingProgress {
  final int totalItems;
  final int packedItems;
  final int unpackedItems;
  final double completionPercentage;

  const PackingProgress({
    this.totalItems = 0,
    this.packedItems = 0,
    this.unpackedItems = 0,
    this.completionPercentage = 0.0,
  });

  factory PackingProgress.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const PackingProgress();
    return PackingProgress(
      totalItems: json['totalItems'] is num ? (json['totalItems'] as num).toInt() : 0,
      packedItems: json['packedItems'] is num ? (json['packedItems'] as num).toInt() : 0,
      unpackedItems: json['unpackedItems'] is num ? (json['unpackedItems'] as num).toInt() : 0,
      completionPercentage: json['completionPercentage'] is num
          ? (json['completionPercentage'] as num).toDouble()
          : 0.0,
    );
  }

  Map<String, dynamic> toJson() => {
        'totalItems': totalItems,
        'packedItems': packedItems,
        'unpackedItems': unpackedItems,
        'completionPercentage': completionPercentage,
      };
}

class PackingWeatherContext {
  final String status;
  final String? source;
  final List<String> dates;
  final String? message;

  const PackingWeatherContext({
    this.status = 'unavailable',
    this.source,
    this.dates = const [],
    this.message,
  });

  bool get isAvailable => status == 'available';
  bool get isUnavailable => status == 'unavailable';

  factory PackingWeatherContext.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const PackingWeatherContext();
    return PackingWeatherContext(
      status: (json['status'] ?? 'unavailable').toString(),
      source: json['source']?.toString(),
      dates: json['dates'] is List
          ? (json['dates'] as List).map((e) => e.toString()).toList()
          : const [],
      message: json['message']?.toString(),
    );
  }

  Map<String, dynamic> toJson() => {
        'status': status,
        if (source != null) 'source': source,
        'dates': dates,
        if (message != null) 'message': message,
      };
}

class PackingChanges {
  final bool created;
  final int added;
  final int inactive;

  const PackingChanges({
    this.created = false,
    this.added = 0,
    this.inactive = 0,
  });

  factory PackingChanges.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const PackingChanges();
    return PackingChanges(
      created: json['created'] == true,
      added: json['added'] is num ? (json['added'] as num).toInt() : 0,
      inactive: json['inactive'] is num ? (json['inactive'] as num).toInt() : 0,
    );
  }

  Map<String, dynamic> toJson() => {
        'created': created,
        'added': added,
        'inactive': inactive,
      };
}

class PackingChecklist {
  final String checklistId;
  final String tripId;
  final int schemaVersion;
  final int ruleVersion;
  final int revision;
  final String createdAt;
  final String updatedAt;
  final String generatedAt;
  final Map<String, dynamic> tripContext;
  final PackingWeatherContext weatherContext;
  final List<PackingItem> items;

  const PackingChecklist({
    required this.checklistId,
    required this.tripId,
    this.schemaVersion = 1,
    this.ruleVersion = 1,
    required this.revision,
    this.createdAt = '',
    this.updatedAt = '',
    this.generatedAt = '',
    this.tripContext = const {},
    this.weatherContext = const PackingWeatherContext(),
    this.items = const [],
  });

  List<PackingItem> get activeItems => items.where((i) => i.isActive).toList();
  List<PackingItem> get suppressedItems => items.where((i) => i.isSuppressed).toList();
  List<PackingItem> get inactiveItems => items.where((i) => i.isInactive).toList();

  List<PackingItem> itemsForCategory(String categoryId) =>
      activeItems.where((i) => i.category == categoryId).toList();

  factory PackingChecklist.fromJson(Map<String, dynamic> json) {
    return PackingChecklist(
      checklistId: (json['checklistId'] ?? '').toString(),
      tripId: (json['tripId'] ?? '').toString(),
      schemaVersion: json['schemaVersion'] is num
          ? (json['schemaVersion'] as num).toInt()
          : 1,
      ruleVersion: json['ruleVersion'] is num
          ? (json['ruleVersion'] as num).toInt()
          : 1,
      revision: json['revision'] is num
          ? (json['revision'] as num).toInt()
          : 1,
      createdAt: (json['createdAt'] ?? '').toString(),
      updatedAt: (json['updatedAt'] ?? '').toString(),
      generatedAt: (json['generatedAt'] ?? '').toString(),
      tripContext: json['tripContext'] is Map
          ? Map<String, dynamic>.from(json['tripContext'] as Map)
          : const {},
      weatherContext: PackingWeatherContext.fromJson(
        json['weatherContext'] is Map
            ? Map<String, dynamic>.from(json['weatherContext'] as Map)
            : null,
      ),
      items: json['items'] is List
          ? (json['items'] as List)
              .whereType<Map>()
              .map((e) => PackingItem.fromJson(Map<String, dynamic>.from(e)))
              .toList()
          : const [],
    );
  }

  Map<String, dynamic> toJson() => {
        'checklistId': checklistId,
        'tripId': tripId,
        'schemaVersion': schemaVersion,
        'ruleVersion': ruleVersion,
        'revision': revision,
        'createdAt': createdAt,
        'updatedAt': updatedAt,
        'generatedAt': generatedAt,
        'tripContext': tripContext,
        'weatherContext': weatherContext.toJson(),
        'items': items.map((i) => i.toJson()).toList(),
      };
}

class PackingChecklistResponse {
  final bool ok;
  final String state; // 'not_generated', 'empty', 'ready'
  final PackingChecklist? checklist;
  final List<PackingCategory> categories;
  final PackingProgress progress;
  final PackingWeatherContext weatherContext;
  final bool needsRefresh;
  final PackingChanges? changes;
  final String? error;
  final int? currentRevision;

  const PackingChecklistResponse({
    required this.ok,
    this.state = 'not_generated',
    this.checklist,
    this.categories = const [],
    this.progress = const PackingProgress(),
    this.weatherContext = const PackingWeatherContext(),
    this.needsRefresh = false,
    this.changes,
    this.error,
    this.currentRevision,
  });

  bool get isNotGenerated => state == 'not_generated' || checklist == null;
  bool get isEmpty => state == 'empty' || (checklist != null && checklist!.activeItems.isEmpty);
  bool get isReady => state == 'ready' && checklist != null && checklist!.activeItems.isNotEmpty;

  factory PackingChecklistResponse.fromJson(Map<String, dynamic> json) {
    return PackingChecklistResponse(
      ok: json['ok'] == true,
      state: (json['state'] ?? 'not_generated').toString(),
      checklist: json['checklist'] is Map
          ? PackingChecklist.fromJson(Map<String, dynamic>.from(json['checklist'] as Map))
          : null,
      categories: json['categories'] is List
          ? (json['categories'] as List)
              .whereType<Map>()
              .map((e) => PackingCategory.fromJson(Map<String, dynamic>.from(e)))
              .toList()
          : defaultCategories,
      progress: PackingProgress.fromJson(
        json['progress'] is Map
            ? Map<String, dynamic>.from(json['progress'] as Map)
            : null,
      ),
      weatherContext: PackingWeatherContext.fromJson(
        json['weatherContext'] is Map
            ? Map<String, dynamic>.from(json['weatherContext'] as Map)
            : null,
      ),
      needsRefresh: json['needsRefresh'] == true,
      changes: json['changes'] is Map
          ? PackingChanges.fromJson(Map<String, dynamic>.from(json['changes'] as Map))
          : null,
      error: json['error']?.toString(),
      currentRevision: json['currentRevision'] is num
          ? (json['currentRevision'] as num).toInt()
          : null,
    );
  }

  static const defaultCategories = [
    PackingCategory(id: 'documents', name: 'Travel Documents'),
    PackingCategory(id: 'clothing', name: 'Clothing'),
    PackingCategory(id: 'personal_care', name: 'Personal Care & Toiletries'),
    PackingCategory(id: 'electronics', name: 'Electronics'),
    PackingCategory(id: 'activity', name: 'Activity Essentials'),
    PackingCategory(id: 'weather', name: 'Weather Essentials'),
    PackingCategory(id: 'miscellaneous', name: 'Miscellaneous'),
  ];
}
