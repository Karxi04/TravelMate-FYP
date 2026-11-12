import 'dart:async';
import 'dart:convert';
import 'dart:math';

import 'package:flutter/services.dart';
import 'package:http/http.dart' as http;

const _channel = MethodChannel('travelmate/local_backend');

typedef LocalNetwork = ({int handle, List<String> subnets});
typedef _Selection = ({String network, Uri origin, DateTime expires});

Future<LocalNetwork?> androidLocalNetwork() async {
  final result = await _channel.invokeMapMethod<String, dynamic>('network');
  if (result == null) return null;
  return (
    handle: result['handle'] as int,
    subnets: (result['subnets'] as List).cast<String>(),
  );
}

Future<bool> verifyLocalBackendProof(
    String publicKey, String message, String proof) async {
  return await _channel.invokeMethod<bool>('verify', {
        'publicKey': publicKey,
        'message': message,
        'proof': proof,
      }) ??
      false;
}

int? _ipv4(String host) {
  final octets = host.split('.');
  if (octets.length != 4) return null;
  var value = 0;
  for (final octet in octets) {
    final part = int.tryParse(octet);
    if (part == null || part < 0 || part > 255 || '$part' != octet) return null;
    value = (value << 8) | part;
  }
  return value;
}

Uri privateLanOrigin(String value) {
  final origin = Uri.tryParse(value.trim().replaceFirst(RegExp(r'/+$'), ''));
  final address = _ipv4(origin?.host ?? '');
  final private = address != null &&
      (address >> 24 == 10 ||
          address >> 20 == 0xac1 ||
          address >> 16 == 0xc0a8) &&
      !{'10.0.2.2', '10.0.3.2'}.contains(origin?.host);
  if (origin == null ||
      !private ||
      origin.port < 1024 ||
      origin.port > 65535 ||
      origin.toString() != 'http://${origin.host}:${origin.port}') {
    throw StateError(
        'Local Backend addresses must be private HTTP IPv4 origins with an explicit port.');
  }
  return origin;
}

class LocalBackend {
  final List<Uri> _origins;
  final String publicKey;
  final Future<LocalNetwork?> Function() network;
  final Future<bool> Function(String, String, String) verify;
  final http.Client Function() client;
  final _random = Random.secure();
  final _probes = <String, Future<_Selection>>{};
  _Selection? _verified;
  String? _writeNetwork;
  Uri? _writeOrigin;
  int _writes = 0;

  LocalBackend({
    required String primary,
    required String alternate,
    required this.publicKey,
    this.network = androidLocalNetwork,
    this.verify = verifyLocalBackendProof,
    this.client = http.Client.new,
  }) : _origins = [privateLanOrigin(primary), privateLanOrigin(alternate)] {
    if (_origins.first == _origins.last ||
        _origins.first.port != _origins.last.port ||
        publicKey.isEmpty) {
      throw StateError(
          'Local Backend selection requires two distinct addresses on one port and a pinned public key.');
    }
  }

  String _networkKey(LocalNetwork value) =>
      '${value.handle}:${(value.subnets.toList()..sort()).join(",")}';

  bool _reachableOn(Uri origin, String subnet) {
    final parts = subnet.split('/');
    if (parts.length != 2) return false;
    final address = _ipv4(parts.first);
    final prefix = int.tryParse(parts.last);
    if (address == null || prefix == null || prefix < 8 || prefix > 32) {
      return false;
    }
    return address >> (32 - prefix) == _ipv4(origin.host)! >> (32 - prefix);
  }

  Future<http.Response> _send(http.Request request, Duration timeout) async {
    final transport = client();
    try {
      request.followRedirects = false;
      final response = await transport
          .send(request)
          .then(http.Response.fromStream)
          .timeout(timeout);
      if (response.statusCode >= 300 && response.statusCode < 400) {
        throw http.ClientException('Unexpected Backend redirect.');
      }
      return response;
    } finally {
      transport.close();
    }
  }

  Future<_Selection> _probe(LocalNetwork current, String key) async {
    for (final origin in _origins) {
      if (!current.subnets.any((subnet) => _reachableOn(origin, subnet)))
        continue;
      final nonce = List.generate(
              32, (_) => _random.nextInt(256).toRadixString(16).padLeft(2, '0'))
          .join();
      final url = origin.replace(
        path: '/api/health',
        queryParameters: {'lanChallenge': nonce},
      );
      try {
        final response =
            await _send(http.Request('GET', url), const Duration(seconds: 3));
        if (response.statusCode != 200) continue;
        final data = jsonDecode(response.body);
        if (data is! Map ||
            data['ok'] != true ||
            data['service'] != 'TravelMate Backend API' ||
            data['lanProof'] is! String) continue;
        if (await verify(publicKey, 'travelmate-local-lan-v1\n$origin\n$nonce',
            data['lanProof'] as String)) {
          return (
            network: key,
            origin: origin,
            expires: DateTime.now().add(const Duration(seconds: 30))
          );
        }
      } on TimeoutException {
        continue;
      } on http.ClientException {
        continue;
      } on FormatException {
        continue;
      }
    }
    throw http.ClientException(
        'No verified TravelMate Backend is reachable on this network.');
  }

  Future<Uri> _select(LocalNetwork current, String key) async {
    if (_writeOrigin != null) return _writeOrigin!;
    final cached = _verified;
    if (cached != null &&
        cached.network == key &&
        cached.expires.isAfter(DateTime.now())) {
      return cached.origin;
    }
    final pending = _probes.putIfAbsent(key, () => _probe(current, key));
    try {
      final selection = await pending;
      _verified = selection;
      return selection.origin;
    } finally {
      if (identical(_probes[key], pending)) _probes.remove(key);
    }
  }

  Future<http.Response> request(
    String method,
    String path, {
    Map<String, String>? query,
    required Future<Map<String, String>> Function() headers,
    String? body,
    required Duration timeout,
  }) async {
    if (!path.startsWith('/api/')) throw ArgumentError.value(path, 'path');
    final current = await network();
    if (current == null)
      throw http.ClientException('No approved local Wi-Fi connection.');
    final key = _networkKey(current);
    if (_writeNetwork != null && _writeNetwork != key) {
      throw http.ClientException(
          'The network changed during a TravelMate update.');
    }
    // Payment reconciliation can persist order changes even though it is GET.
    final isWrite = method != 'GET' ||
        (path.startsWith('/api/fr9/orders/') &&
            Uri.parse(path).path.endsWith('/reconcile'));
    if (isWrite) {
      _writeNetwork = key;
      _writes++;
    }
    try {
      final origin = await _select(current, key);
      if (isWrite) _writeOrigin ??= origin;
      final request = http.Request(
          method, Uri.parse('$origin$path').replace(queryParameters: query));
      request.headers.addAll(await headers());
      if (body != null) request.body = body;
      final latest = await network();
      if (latest == null ||
          _networkKey(latest) != key ||
          (_writeNetwork != null &&
              (_writeNetwork != key || _writeOrigin != origin))) {
        throw http.ClientException(
            'The network changed before the TravelMate request was sent.');
      }
      // Exactly one API send. A later user action can select a newly verified address.
      return await _send(request, timeout);
    } on http.ClientException {
      if (_verified?.network == key) _verified = null;
      rethrow;
    } on TimeoutException {
      if (_verified?.network == key) _verified = null;
      rethrow;
    } finally {
      if (isWrite && --_writes == 0) {
        _writeNetwork = null;
        _writeOrigin = null;
      }
    }
  }
}
