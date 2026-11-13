import 'dart:convert';
import 'package:crypto/crypto.dart';
import 'package:flutter/services.dart';
import 'api_service.dart';

String reminderOwner(String uid) => sha256.convert(utf8.encode(uid)).toString();

bool activeReminderTrip(Map trip) =>
    ![
      'cancelled',
      'canceled',
      'archived',
      'deleted',
      'payment_cancelled',
      'payment_failed'
    ].contains('${trip['status'] ?? ''}'.toLowerCase()) &&
    trip['deletedAt'] == null &&
    trip['fulfillmentStatus'] != 'fulfillment_declined';

/// Trips have calendar dates, not a trip-wide departure time: the owner chose
/// 09:00 Malaysia time on the preceding day. This is not an inferred flight time.
List<Map<String, dynamic>> tripReminderPlan(
    String uid, List trips, DateTime now) {
  final result = <Map<String, dynamic>>[];
  for (final trip in trips.whereType<Map>()) {
    if (trip['travellerId'] != uid || !activeReminderTrip(trip)) continue;
    final id = '${trip['id'] ?? ''}';
    final date = '${trip['startDate'] ?? ''}';
    if (!RegExp(r'^[A-Za-z0-9_-][A-Za-z0-9_:.-]{0,199}$').hasMatch(id) ||
        !RegExp(r'^\d{4}-\d{2}-\d{2}$').hasMatch(date)) continue;
    final start = DateTime.tryParse('${date}T00:00:00+08:00');
    if (start == null ||
        start
                .toUtc()
                .add(const Duration(hours: 8))
                .toIso8601String()
                .substring(0, 10) !=
            date ||
        !start.isAfter(now)) continue;
    final end = trip['endDate'];
    if (end != null &&
        ('$end'.compareTo(date) < 0 || DateTime.tryParse('$end') == null))
      continue;
    final key = sha256
        .convert(utf8.encode(jsonEncode([uid, 'local_trip', id, date])))
        .toString();
    final title = '${trip['title'] ?? trip['destinationArea'] ?? 'Your trip'}';
    result.add({
      'id': key,
      'tripId': id,
      'startDate': date,
      'expiresAt': start.millisecondsSinceEpoch,
      'triggerAt':
          start.subtract(const Duration(hours: 15)).millisecondsSinceEpoch,
      'title': title.substring(0, title.length.clamp(0, 150)),
      'screen': trip['packageTrip'] == true || trip['tripType'] == 'package'
          ? 'package_trip'
          : 'trip'
    });
  }
  return result;
}

class TripReminderPlatform {
  static const channel = MethodChannel('travelmate/notifications');
  Future<bool> available() async =>
      await channel.invokeMethod<bool>('remindersAvailable') ?? false;
  Future<void> clear() => channel.invokeMethod('clearReminders');
  Future<void> adoptOwner(String owner) =>
      channel.invokeMethod('reminderOwner', {'owner': owner});
  Future<void> replace(String owner, List<Map<String, dynamic>> items) async {
    if (await channel.invokeMethod<bool>(
            'replaceReminders', {'owner': owner, 'items': items}) !=
        true) {
      throw StateError('Reminder schedule was not acknowledged.');
    }
  }

  Future<Map?> target(String owner, String id) =>
      channel.invokeMapMethod('reminderTarget', {'owner': owner, 'id': id});
}

class TripReminders {
  final ApiService api;
  final TripReminderPlatform platform;
  String? _owner;
  bool _ownerKnown = false;
  int revision = 0;
  bool capable = false;
  String? problem;
  Future<void> _work = Future.value();
  TripReminders({required this.api, TripReminderPlatform? platform})
      : platform = platform ?? TripReminderPlatform();
  Future<void> _serialize(Future<void> Function() action) {
    final next = _work.then((_) => action());
    _work = next.catchError((Object _) {});
    return next;
  }

  Future<void> changeOwner(String? owner) {
    if (_ownerKnown && _owner == owner) return Future.value();
    _ownerKnown = true;
    _owner = owner;
    revision++;
    problem = null;
    return _serialize(() async {
      try {
        if (owner == null) {
          await platform.clear();
        } else {
          await platform.adoptOwner(reminderOwner(owner));
        }
      } catch (_) {}
    });
  }

  Future<void> refresh(String owner, {required bool allowed, List? trips}) async {
    final version = revision;
    try {
      if (_owner != owner || !await platform.available()) return;
      capable = true;
      if (!allowed) {
        await _serialize(() async {
          if (version == revision) {
            await platform.clear();
          }
        });
        return;
      }
      if (trips == null) {
        final data = await api.get('/api/fr5/itineraries');
        if (data is! Map || data['ok'] != true || data['items'] is! List) {
          throw StateError('Trips unavailable');
        }
        trips = data['items'] as List;
      }
      final plan = tripReminderPlan(owner, trips, DateTime.now().toUtc());
      await _serialize(() async {
        if (_owner != owner || revision != version) return;
        await platform.replace(reminderOwner(owner), plan);
        problem = null;
      });
    } catch (_) {
      if (_owner == owner && revision == version)
        problem =
            'Trip reminders could not be refreshed. Open Trips with a connection and retry.';
    }
  }
}

/// Local alarm taps resolve an owned current trip; they never trust payload URLs.
Future<Map?> localReminderTarget(
    String id, String owner, ApiService api, String? Function() currentOwner,
    {TripReminderPlatform? platform}) async {
  Map? target;
  try {
    target = await (platform ?? TripReminderPlatform())
        .target(reminderOwner(owner), id);
  } on MissingPluginException {
    return null;
  }
  if (target == null || currentOwner() != owner) return null;
  final tripId = '${target['tripId'] ?? ''}';
  if (!RegExp(r'^[A-Za-z0-9_-][A-Za-z0-9_:.-]{0,199}$').hasMatch(tripId))
    return null;
  final response = await api.get('/api/fr5/itineraries/$tripId');
  final trip = response is Map ? response['itinerary'] : null;
  if (currentOwner() != owner ||
      trip is! Map ||
      trip['travellerId'] != owner ||
      !activeReminderTrip(trip)) return null;
  return {
    'screen': trip['packageTrip'] == true || trip['tripType'] == 'package'
        ? 'package_trip'
        : 'trip',
    'tripId': tripId
  };
}
