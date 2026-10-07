import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:travelmate_traveller/services/api_service.dart';

void main() {
  test('debug emulator and desktop defaults remain available', () {
    expect(
        resolveApiBaseUrl('', release: false, platform: TargetPlatform.android),
        'http://10.0.2.2:5000');
    expect(resolveApiBaseUrl('', release: false, web: true),
        'http://127.0.0.1:5000');
    expect(
        resolveApiBaseUrl('', release: false, platform: TargetPlatform.windows),
        'http://127.0.0.1:5000');
  });

  for (final url in [
    '',
    'not-a-url',
    'http://backend.example',
    'https://localhost',
    'https://127.0.0.1',
    'https://[::1]',
    'https://0.0.0.0',
    'http://10.0.2.2:5000',
    'https://10.0.2.2',
    'https://10.0.3.2',
    'https://user:password@backend.example',
    'https://backend.example?token=test',
    'https://backend.example#fragment',
  ]) {
    test('cloud release rejects unsafe or absent URL: $url', () {
      expect(() => resolveApiBaseUrl(url, release: true), throwsStateError);
    });
  }

  test('explicit cloud configuration is accepted and normalized', () {
    expect(resolveApiBaseUrl(' https://backend.example/ ', release: true),
        'https://backend.example');
    expect(resolveApiBaseUrl('https://backend.example/service', release: true),
        'https://backend.example/service');
  });

  test('debug physical device accepts an explicit LAN backend URL', () {
    expect(
      resolveApiBaseUrl('http://172.20.10.5:5000', release: false),
      'http://172.20.10.5:5000',
    );
  });
}
