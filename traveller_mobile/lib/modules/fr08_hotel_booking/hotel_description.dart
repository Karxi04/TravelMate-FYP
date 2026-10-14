import 'package:flutter/material.dart';

class HotelDescription {
  static List<InlineSpan> spans(String source, {required TextStyle bodyStyle}) {
    final safe = source
        .replaceAll(
            RegExp(r'<(script|style)\b[^>]*>[\s\S]*?</\1>',
                caseSensitive: false),
            '')
        .replaceAllMapped(RegExp(r'<[^>]+>', caseSensitive: false),
            (match) => _tag(match.group(0)!));
    final parts = <InlineSpan>[];
    var bold = false;
    for (final token in RegExp(r'\[\[B\]\]|\[\[/B\]\]|[^\[\]]+').allMatches(safe)) {
      final text = token.group(0)!;
      if (text == '[[B]]') {
        bold = true;
      } else if (text == '[[/B]]') {
        bold = false;
      } else if (text.isNotEmpty) {
        parts.add(TextSpan(
          text: _decode(text),
          style: bodyStyle.copyWith(
            fontWeight: bold ? FontWeight.w700 : FontWeight.w400,
            decoration: TextDecoration.none,
            decorationColor: Colors.transparent,
            backgroundColor: Colors.transparent,
          ),
        ));
      }
    }
    return parts;
  }

  static String _tag(String raw) {
    final tag = raw.toLowerCase().replaceAll(RegExp(r'\s+'), '');
    if (tag == '<strong>' || tag == '<b>') return '[[B]]';
    if (tag == '</strong>' || tag == '</b>') return '[[/B]]';
    if (tag == '<br>' || tag == '<br/>' || tag == '<br/>') return '\n';
    if (tag == '<li>') return '\n• ';
    if (tag == '</li>' || tag == '<p>' || tag == '</p>' || tag == '<div>' || tag == '</div>') return '\n';
    return '';
  }

  static String _decode(String value) => value
      .replaceAll('&amp;', '&')
      .replaceAll('&lt;', '<')
      .replaceAll('&gt;', '>')
      .replaceAll('&quot;', '"')
      .replaceAll('&#39;', "'");
}
