import 'package:flutter/material.dart';
import '../theme/app_theme.dart';
import '../services/place_image_service.dart';

class TravelSectionHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const TravelSectionHeader({
    super.key,
    required this.title,
    this.subtitle,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.end,
      children: [
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  fontSize: 21,
                  fontWeight: FontWeight.w800,
                  color: InkWashColors.ink,
                ),
              ),
              if (subtitle != null) ...[
                const SizedBox(height: 3),
                Text(
                  subtitle!,
                  style: const TextStyle(
                    color: InkWashColors.mutedInk,
                    fontSize: 13,
                  ),
                ),
              ],
            ],
          ),
        ),
        if (actionLabel != null && onAction != null)
          TextButton(onPressed: onAction, child: Text(actionLabel!)),
      ],
    );
  }
}

class TravelQuickAction extends StatelessWidget {
  final IconData icon;
  final String label;
  final String subtitle;
  final VoidCallback onTap;

  const TravelQuickAction({
    super.key,
    required this.icon,
    required this.label,
    required this.subtitle,
    required this.onTap,
  });

  @override
  Widget build(BuildContext context) {
    return Material(
      color: Colors.white,
      borderRadius: BorderRadius.circular(18),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(18),
        child: Container(
          padding: const EdgeInsets.all(14),
          decoration: BoxDecoration(
            border: Border.all(color: const Color(0xFFE3E3DE)),
            borderRadius: BorderRadius.circular(18),
          ),
          child: Row(
            children: [
              Container(
                width: 44,
                height: 44,
                decoration: BoxDecoration(
                  color: InkWashColors.paleBlue,
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: InkWashColors.blueGrey),
              ),
              const SizedBox(width: 11),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: const TextStyle(fontWeight: FontWeight.w800)),
                    Text(
                      subtitle,
                      style: const TextStyle(
                        color: InkWashColors.mutedInk,
                        fontSize: 12,
                      ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded, color: InkWashColors.softGrey),
            ],
          ),
        ),
      ),
    );
  }
}

class TravelEmptyState extends StatelessWidget {
  final IconData icon;
  final String title;
  final String message;
  final String? actionLabel;
  final VoidCallback? onAction;

  const TravelEmptyState({
    super.key,
    required this.icon,
    required this.title,
    required this.message,
    this.actionLabel,
    this.onAction,
  });

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(24),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFE3E3DE)),
      ),
      child: Column(
        children: [
          CircleAvatar(
            radius: 27,
            backgroundColor: InkWashColors.paleBlue,
            child: Icon(icon, color: InkWashColors.blueGrey),
          ),
          const SizedBox(height: 12),
          Text(title, style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w800)),
          const SizedBox(height: 5),
          Text(
            message,
            textAlign: TextAlign.center,
            style: const TextStyle(color: InkWashColors.mutedInk),
          ),
          if (actionLabel != null && onAction != null) ...[
            const SizedBox(height: 8),
            TextButton(onPressed: onAction, child: Text(actionLabel!)),
          ],
        ],
      ),
    );
  }
}

class TravelStatusPill extends StatelessWidget {
  final String text;
  final IconData? icon;

  const TravelStatusPill({super.key, required this.text, this.icon});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
      decoration: BoxDecoration(
        color: InkWashColors.paleBlue,
        borderRadius: BorderRadius.circular(30),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: 14, color: InkWashColors.blueGrey),
            const SizedBox(width: 5),
          ],
          Text(
            text,
            style: const TextStyle(
              color: InkWashColors.charcoal,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
        ],
      ),
    );
  }
}

class TravelPlaceImage extends StatelessWidget {
  final Map<String, dynamic> place;
  final double height;
  final double? width;
  final BorderRadius borderRadius;

  const TravelPlaceImage({
    super.key,
    required this.place,
    this.height = 150,
    this.width,
    this.borderRadius = const BorderRadius.all(Radius.circular(18)),
  });

  String get _title =>
      (place['title'] ?? place['name'] ?? 'Travel destination').toString();

  String get _category =>
      (place['category'] ?? place['type'] ?? 'Place').toString();

  IconData _fallbackIcon() {
    final value = '$_title $_category'.toLowerCase();
    if (value.contains('food') ||
        value.contains('restaurant') ||
        value.contains('mee') ||
        value.contains('laksa') ||
        value.contains('cendol') ||
        value.contains('hawker')) {
      return Icons.restaurant_rounded;
    }
    if (value.contains('museum') ||
        value.contains('heritage') ||
        value.contains('culture') ||
        value.contains('temple') ||
        value.contains('mosque')) {
      return Icons.account_balance_rounded;
    }
    if (value.contains('nature') ||
        value.contains('garden') ||
        value.contains('park') ||
        value.contains('hill')) {
      return Icons.park_rounded;
    }
    if (value.contains('shop') || value.contains('market')) {
      return Icons.shopping_bag_rounded;
    }
    return Icons.landscape_rounded;
  }

  Widget _fallback() {
    return Container(
      color: InkWashColors.paleBlue,
      alignment: Alignment.center,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            _fallbackIcon(),
            color: InkWashColors.blueGrey,
            size: 38,
          ),
          const SizedBox(height: 7),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12),
            child: Text(
              _title,
              maxLines: 1,
              overflow: TextOverflow.ellipsis,
              textAlign: TextAlign.center,
              style: const TextStyle(
                color: InkWashColors.mutedInk,
                fontWeight: FontWeight.w700,
                fontSize: 11,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return ClipRRect(
      borderRadius: borderRadius,
      child: SizedBox(
        width: width,
        height: height,
        child: FutureBuilder<String?>(
          future: PlaceImageService.resolve(place),
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return Container(
                color: InkWashColors.paleBlue,
                alignment: Alignment.center,
                child: const SizedBox(
                  width: 22,
                  height: 22,
                  child: CircularProgressIndicator(strokeWidth: 2),
                ),
              );
            }

            final url = snapshot.data;
            if (url == null || url.isEmpty) return _fallback();

            return Image.network(
              url,
              fit: BoxFit.cover,
              gaplessPlayback: true,
              errorBuilder: (context, error, stackTrace) => _fallback(),
              loadingBuilder: (context, child, progress) {
                if (progress == null) return child;
                return Container(
                  color: InkWashColors.paleBlue,
                  alignment: Alignment.center,
                  child: const SizedBox(
                    width: 22,
                    height: 22,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
