import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import '../theme/app_theme.dart';
import '../services/place_image_service.dart';

class TravelMatePageScaffold extends StatelessWidget {
  final PreferredSizeWidget? appBar;
  final Widget body;
  final Widget? floatingActionButton;
  final Widget? bottomNavigationBar;
  final bool safeArea;
  final EdgeInsetsGeometry padding;

  const TravelMatePageScaffold({
    super.key,
    this.appBar,
    required this.body,
    this.floatingActionButton,
    this.bottomNavigationBar,
    this.safeArea = true,
    this.padding = AppSpacing.page,
  });

  @override
  Widget build(BuildContext context) {
    Widget content = Padding(padding: padding, child: body);
    if (safeArea) content = SafeArea(child: content);
    return Scaffold(
      appBar: appBar,
      body: content,
      floatingActionButton: floatingActionButton,
      bottomNavigationBar: bottomNavigationBar,
    );
  }
}

class AppSectionHeader extends StatelessWidget {
  final String title;
  final String? subtitle;
  final String? actionLabel;
  final VoidCallback? onAction;

  const AppSectionHeader({
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
                style: Theme.of(context).textTheme.headlineSmall,
              ),
              if (subtitle != null) ...[
                const SizedBox(height: AppSpacing.xxs),
                Text(
                  subtitle!,
                  style: Theme.of(context).textTheme.bodySmall?.copyWith(
                        color: AppColors.textSecondary,
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
  Widget build(BuildContext context) => AppSectionHeader(
        title: title,
        subtitle: subtitle,
        actionLabel: actionLabel,
        onAction: onAction,
      );
}

class PrimaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool loading;

  const PrimaryButton({
    super.key,
    required this.label,
    required this.onPressed,
    this.icon,
    this.loading = false,
  });

  @override
  Widget build(BuildContext context) {
    final child = loading
        ? const SizedBox.square(
            dimension: AppSizes.icon,
            child:
                CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
          )
        : Text(label);
    if (icon != null && !loading) {
      return FilledButton.icon(
          onPressed: onPressed, icon: Icon(icon), label: child);
    }
    return FilledButton(onPressed: loading ? null : onPressed, child: child);
  }
}

class SecondaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;

  const SecondaryButton(
      {super.key, required this.label, required this.onPressed, this.icon});

  @override
  Widget build(BuildContext context) {
    if (icon != null) {
      return OutlinedButton.icon(
          onPressed: onPressed, icon: Icon(icon), label: Text(label));
    }
    return OutlinedButton(onPressed: onPressed, child: Text(label));
  }
}

class TertiaryButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;

  const TertiaryButton(
      {super.key, required this.label, required this.onPressed, this.icon});

  @override
  Widget build(BuildContext context) {
    if (icon != null) {
      return TextButton.icon(
          onPressed: onPressed, icon: Icon(icon), label: Text(label));
    }
    return TextButton(onPressed: onPressed, child: Text(label));
  }
}

class DestructiveButton extends StatelessWidget {
  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;

  const DestructiveButton(
      {super.key, required this.label, required this.onPressed, this.icon});

  @override
  Widget build(BuildContext context) {
    final style = OutlinedButton.styleFrom(
      foregroundColor: AppColors.error,
      side: const BorderSide(color: AppColors.error),
    );
    if (icon != null) {
      return OutlinedButton.icon(
        style: style,
        onPressed: onPressed,
        icon: Icon(icon),
        label: Text(label),
      );
    }
    return OutlinedButton(
        style: style, onPressed: onPressed, child: Text(label));
  }
}

class AppTextField extends StatelessWidget {
  final TextEditingController? controller;
  final String? label;
  final String? hint;
  final String? errorText;
  final IconData? prefixIcon;
  final Widget? suffixIcon;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final TextInputAction? textInputAction;
  final TextInputType? keyboardType;
  final List<TextInputFormatter>? inputFormatters;
  final bool readOnly;
  final VoidCallback? onTap;
  final bool enabled;
  final int maxLines;

  const AppTextField({
    super.key,
    this.controller,
    this.label,
    this.hint,
    this.errorText,
    this.prefixIcon,
    this.suffixIcon,
    this.onChanged,
    this.onSubmitted,
    this.textInputAction,
    this.keyboardType,
    this.inputFormatters,
    this.readOnly = false,
    this.onTap,
    this.enabled = true,
    this.maxLines = 1,
  });

  @override
  Widget build(BuildContext context) {
    return TextField(
      controller: controller,
      enabled: enabled,
      maxLines: maxLines,
      textInputAction: textInputAction,
      keyboardType: keyboardType,
      inputFormatters: inputFormatters,
      readOnly: readOnly,
      onTap: onTap,
      onChanged: onChanged,
      onSubmitted: onSubmitted,
      decoration: InputDecoration(
        labelText: label,
        hintText: hint,
        errorText: errorText,
        prefixIcon: prefixIcon == null ? null : Icon(prefixIcon),
        suffixIcon: suffixIcon,
      ),
    );
  }
}

class SearchField extends StatelessWidget {
  final TextEditingController? controller;
  final String hint;
  final ValueChanged<String>? onChanged;
  final ValueChanged<String>? onSubmitted;
  final VoidCallback? onClear;

  const SearchField({
    super.key,
    this.controller,
    this.hint = 'Search destinations',
    this.onChanged,
    this.onSubmitted,
    this.onClear,
  });

  @override
  Widget build(BuildContext context) => AppTextField(
        controller: controller,
        hint: hint,
        prefixIcon: Icons.search_rounded,
        onChanged: onChanged,
        onSubmitted: onSubmitted,
        textInputAction: TextInputAction.search,
        suffixIcon: onClear == null
            ? null
            : IconButton(
                tooltip: 'Clear search',
                onPressed: onClear,
                icon: const Icon(Icons.close_rounded),
              ),
      );
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
      color: AppColors.surface,
      borderRadius: AppRadii.card,
      child: InkWell(
        onTap: onTap,
        borderRadius: AppRadii.card,
        child: Container(
          padding: AppSpacing.card,
          decoration: BoxDecoration(
            border: Border.all(color: AppColors.divider),
            borderRadius: AppRadii.card,
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
              const SizedBox(width: AppSpacing.sm),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(label, style: Theme.of(context).textTheme.titleMedium),
                    Text(
                      subtitle,
                      style: Theme.of(context).textTheme.bodySmall?.copyWith(
                            color: AppColors.textSecondary,
                          ),
                    ),
                  ],
                ),
              ),
              const Icon(Icons.chevron_right_rounded,
                  color: InkWashColors.softGrey),
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
      padding: const EdgeInsets.all(AppSpacing.xl),
      decoration: BoxDecoration(
        color: AppColors.surface,
        borderRadius: AppRadii.card,
        border: Border.all(color: AppColors.divider),
      ),
      child: Column(
        children: [
          CircleAvatar(
            radius: 27,
            backgroundColor: InkWashColors.paleBlue,
            child: Icon(icon, color: InkWashColors.blueGrey),
          ),
          const SizedBox(height: AppSpacing.sm),
          Text(title, style: Theme.of(context).textTheme.titleLarge),
          const SizedBox(height: AppSpacing.xxs),
          Text(
            message,
            textAlign: TextAlign.center,
            style: Theme.of(context).textTheme.bodyMedium?.copyWith(
                  color: AppColors.textSecondary,
                ),
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

class AppLoadingState extends StatelessWidget {
  final String message;

  const AppLoadingState({super.key, this.message = 'Loading…'});

  @override
  Widget build(BuildContext context) => Semantics(
        liveRegion: true,
        label: message,
        child: Center(
          child: Padding(
            padding: const EdgeInsets.all(AppSpacing.xl),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                const CircularProgressIndicator(),
                const SizedBox(height: AppSpacing.md),
                Text(message, style: Theme.of(context).textTheme.bodyMedium),
              ],
            ),
          ),
        ),
      );
}

class AppErrorState extends StatelessWidget {
  final String title;
  final String message;
  final String retryLabel;
  final VoidCallback? onRetry;

  const AppErrorState({
    super.key,
    this.title = 'Something went wrong',
    required this.message,
    this.retryLabel = 'Try again',
    this.onRetry,
  });

  @override
  Widget build(BuildContext context) => TravelEmptyState(
        icon: Icons.error_outline_rounded,
        title: title,
        message: message,
        actionLabel: onRetry == null ? null : retryLabel,
        onAction: onRetry,
      );
}

enum AppStatusTone { neutral, info, success, warning, error }

class StatusChip extends StatelessWidget {
  final String text;
  final IconData? icon;
  final AppStatusTone tone;

  const StatusChip({
    super.key,
    required this.text,
    this.icon,
    this.tone = AppStatusTone.info,
  });

  (Color, Color) get _colors => switch (tone) {
        AppStatusTone.neutral => (
            AppColors.surfaceElevated,
            AppColors.textSecondary
          ),
        AppStatusTone.info => (AppColors.infoSoft, AppColors.info),
        AppStatusTone.success => (AppColors.successSoft, AppColors.success),
        AppStatusTone.warning => (AppColors.warningSoft, AppColors.warning),
        AppStatusTone.error => (AppColors.errorSoft, AppColors.error),
      };

  @override
  Widget build(BuildContext context) {
    final (background, foreground) = _colors;
    return Container(
      padding: const EdgeInsets.symmetric(
          horizontal: AppSpacing.sm, vertical: AppSpacing.xs),
      decoration: BoxDecoration(
        color: background,
        borderRadius: BorderRadius.circular(AppRadii.pill),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          if (icon != null) ...[
            Icon(icon, size: AppSizes.iconSmall, color: foreground),
            const SizedBox(width: AppSpacing.xxs),
          ],
          Flexible(
            child: Text(
              text,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: Theme.of(context)
                  .textTheme
                  .labelMedium
                  ?.copyWith(color: foreground),
            ),
          ),
        ],
      ),
    );
  }
}

class SourceFallbackBadge extends StatelessWidget {
  final String source;

  const SourceFallbackBadge({super.key, required this.source});

  @override
  Widget build(BuildContext context) {
    final normalized = source.trim().toLowerCase();
    final isLive = normalized == 'live' || normalized == 'provider';
    final isCache = normalized == 'cache' || normalized == 'cached';
    final label = isLive
        ? 'Live source'
        : (isCache ? 'Cached source' : 'Fallback source');
    final tone = isLive
        ? AppStatusTone.success
        : (isCache ? AppStatusTone.info : AppStatusTone.warning);
    final icon = isLive
        ? Icons.cloud_done_outlined
        : (isCache ? Icons.cached_rounded : Icons.offline_bolt_outlined);
    return StatusChip(text: label, icon: icon, tone: tone);
  }
}

class TravelStatusPill extends StatelessWidget {
  final String text;
  final IconData? icon;

  const TravelStatusPill({super.key, required this.text, this.icon});

  @override
  Widget build(BuildContext context) {
    return StatusChip(text: text, icon: icon);
  }
}

class TravelPlaceImage extends StatefulWidget {
  final Map<String, dynamic> place;
  final double? height;
  final double? width;
  final double? aspectRatio;
  final BorderRadius borderRadius;
  final bool showTitleInFallback;

  const TravelPlaceImage({
    super.key,
    required this.place,
    this.height = 150,
    this.width,
    this.aspectRatio,
    this.borderRadius = const BorderRadius.all(Radius.circular(18)),
    this.showTitleInFallback = false,
  });

  @override
  State<TravelPlaceImage> createState() => _TravelPlaceImageState();
}

class _TravelPlaceImageState extends State<TravelPlaceImage> {
  static const int _maxAutoRetries = 3;

  late Future<String?> _imageFuture;
  int _imageRevision = 0;
  int _autoRecoveryAttempts = 0;
  String? _failedUrlBeingHandled;
  bool _isExhausted = false;

  Map<String, dynamic> get place => widget.place;
  double? get height => widget.height;
  double? get width => widget.width;
  double? get aspectRatio => widget.aspectRatio;
  BorderRadius get borderRadius => widget.borderRadius;

  @override
  void initState() {
    super.initState();
    _imageFuture = PlaceImageService.resolve(place);
  }

  @override
  void didUpdateWidget(covariant TravelPlaceImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    final oldKey = PlaceImageService.placeKeyFor(oldWidget.place);
    final newKey = PlaceImageService.placeKeyFor(widget.place);
    final oldUrls =
        PlaceImageService.explicitImageUrlsForTesting(oldWidget.place);
    final newUrls =
        PlaceImageService.explicitImageUrlsForTesting(widget.place);
    final urlsChanged = oldUrls.length != newUrls.length ||
        !oldUrls.every(newUrls.contains);

    if (oldKey != newKey || urlsChanged) {
      _autoRecoveryAttempts = 0;
      _isExhausted = false;
      _failedUrlBeingHandled = null;
      _imageRevision = 0;
      _imageFuture = PlaceImageService.resolve(place);
    }
  }

  String get _title => (place['title'] ??
          place['name'] ??
          place['activityName'] ??
          'Travel destination')
      .toString();

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

  void _scheduleAutoRecovery(String failedUrl) {
    if (_isExhausted || _failedUrlBeingHandled == failedUrl) return;
    _failedUrlBeingHandled = failedUrl;

    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      if (_autoRecoveryAttempts >= _maxAutoRetries) {
        setState(() {
          _isExhausted = true;
        });
        return;
      }

      _autoRecoveryAttempts += 1;
      setState(() {
        _imageRevision += 1;
        _imageFuture = PlaceImageService.markFailedAndResolve(
          place,
          failedUrl: failedUrl,
        ).then((nextUrl) {
          if (nextUrl == null) {
            _isExhausted = true;
          }
          return nextUrl;
        });
      });
    });
  }

  void _retry([String? failedUrl]) {
    setState(() {
      _autoRecoveryAttempts = 0;
      _isExhausted = false;
      _failedUrlBeingHandled = null;
      _imageRevision += 1;
      _imageFuture = PlaceImageService.retry(place, failedUrl: failedUrl);
    });
  }

  Widget _fallback([String? failedUrl]) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final compact =
            constraints.maxHeight <= 110 || constraints.maxWidth <= 110;
        return Container(
          color: InkWashColors.paleBlue,
          alignment: Alignment.center,
          child: Stack(
            fit: StackFit.expand,
            children: [
              Center(
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Icon(
                      _fallbackIcon(),
                      color: InkWashColors.blueGrey,
                      size: compact ? 28 : 38,
                    ),
                    if (!compact && widget.showTitleInFallback) ...[
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
                  ],
                ),
              ),
              Positioned(
                right: 0,
                bottom: 0,
                child: IconButton(
                  key: const ValueKey('place-image-retry'),
                  tooltip: 'Retry image',
                  visualDensity: VisualDensity.compact,
                  iconSize: compact ? 16 : 20,
                  onPressed: () => _retry(failedUrl),
                  icon: const Icon(Icons.refresh_rounded),
                ),
              ),
            ],
          ),
        );
      },
    );
  }

  @override
  Widget build(BuildContext context) {
    final image = FutureBuilder<String?>(
      future: _imageFuture,
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
        if (url == null || url.isEmpty || _isExhausted) return _fallback();

        return Image.network(
          url,
          key: ValueKey('place-image-$url-$_imageRevision'),
          fit: BoxFit.cover,
          gaplessPlayback: true,
          excludeFromSemantics: true,
          errorBuilder: (context, error, stackTrace) {
            _scheduleAutoRecovery(url);
            return _fallback(url);
          },
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
    );

    final sizedImage = aspectRatio == null
        ? SizedBox(width: width, height: height, child: image)
        : SizedBox(
            width: width,
            child: AspectRatio(aspectRatio: aspectRatio!, child: image),
          );

    return Semantics(
      image: true,
      label: 'Image of $_title',
      child: ClipRRect(
        borderRadius: borderRadius,
        child: sizedImage,
      ),
    );
  }
}
