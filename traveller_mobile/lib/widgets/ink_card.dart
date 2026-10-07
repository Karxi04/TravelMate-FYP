import 'package:flutter/material.dart';
import '../theme/app_theme.dart';

class InkCard extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? color;
  const InkCard({
    super.key,
    required this.child,
    this.padding = AppSpacing.card,
    this.color,
  });

  @override
  Widget build(BuildContext context) {
    return Card(
      color: color,
      child: Padding(padding: padding, child: child),
    );
  }
}

class SectionTitle extends StatelessWidget {
  final String title;
  final String? subtitle;
  const SectionTitle(this.title, {super.key, this.subtitle});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Text(title, style: Theme.of(context).textTheme.headlineMedium),
        if (subtitle != null) ...[
          const SizedBox(height: AppSpacing.xxs),
          Text(
            subtitle!,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
          ),
        ],
      ]),
    );
  }
}

String travellerErrorMessage(Object error) {
  final text = error.toString().replaceFirst('Exception: ', '').trim();
  final lower = text.toLowerCase();
  if (lower.contains('timeout') || lower.contains('socket') || lower.contains('connection') || lower.contains('network')) {
    return 'We couldn’t connect to TravelMate. Check your connection and try again.';
  }
  if (lower.contains('unauthorized') || lower.contains('token')) {
    return 'Your session has expired. Sign in again and try again.';
  }
  if (lower.contains('not found')) return 'That TravelMate record is no longer available.';
  if (text.isEmpty || text.length > 180) return 'TravelMate could not complete that request. Please try again.';
  return text;
}

void showError(BuildContext context, Object error) {
  ScaffoldMessenger.of(context).showSnackBar(
    SnackBar(content: Text(travellerErrorMessage(error))),
  );
}
