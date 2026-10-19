import 'dart:math' as math;

import 'package:flutter/material.dart';

import '../../theme/app_theme.dart';
import '../../widgets/travel_widgets.dart';

/// Horizontally swipeable image carousel for Tourism Packages.
///
/// Handles cover image and gallery images, filters out duplicates,
/// supports touch swiping, photo counter pill (e.g. 1/4), and tapping
/// to open the interactive fullscreen viewer.
class PackageGalleryCarousel extends StatefulWidget {
  final List<String> photos;
  final String title;
  final String destination;
  final String? fallbackHeroUrl;
  final double height;
  final BorderRadius? borderRadius;

  const PackageGalleryCarousel({
    super.key,
    required this.photos,
    required this.title,
    this.destination = '',
    this.fallbackHeroUrl,
    this.height = 220,
    this.borderRadius,
  });

  /// Extracts and deduplicates authoritative package photos in order:
  /// 1. Authoritative Cover (`heroImage` / `imageUrl`)
  /// 2. Gallery photos (`galleryImages`, `photos`, or `images`)
  ///
  /// Filters out duplicates, empty strings, and non-HTTP(S) URLs while
  /// strictly preserving the original gallery ordering.
  static List<String> extractPhotos(Map<String, dynamic> item) {
    final photos = <String>[];
    final seen = <String>{};

    void addUrl(dynamic raw) {
      if (raw == null) return;
      final url = raw.toString().trim();
      if (url.isEmpty) return;
      if (!url.startsWith('http://') && !url.startsWith('https://')) return;
      if (seen.add(url)) {
        photos.add(url);
      }
    }

    // Authoritative Cover photo first
    final hero = (item['heroImage'] ?? item['imageUrl'])?.toString().trim();
    addUrl(hero);

    // Gallery images in order
    final rawGallery = item['galleryImages'];
    if (rawGallery is List) {
      for (final element in rawGallery) {
        if (element is Map) {
          addUrl(element['url'] ?? element['imageUrl'] ?? element['image']);
        } else {
          addUrl(element);
        }
      }
    } else if (rawGallery is String && rawGallery.isNotEmpty) {
      addUrl(rawGallery);
    }

    // Fallback to photos or images if galleryImages was not provided
    if (rawGallery == null) {
      final rawPhotos = item['photos'] ?? item['images'];
      if (rawPhotos is List) {
        for (final element in rawPhotos) {
          if (element is Map) {
            addUrl(element['url'] ?? element['imageUrl'] ?? element['image']);
          } else {
            addUrl(element);
          }
        }
      }
    }

    return photos;
  }

  @override
  State<PackageGalleryCarousel> createState() => _PackageGalleryCarouselState();
}

class _PackageGalleryCarouselState extends State<PackageGalleryCarousel> {
  late final PageController _controller;
  int _currentIndex = 0;

  @override
  void initState() {
    super.initState();
    _controller = PageController();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _openFullscreen(BuildContext context, int initialIndex) {
    Navigator.of(context).push(
      MaterialPageRoute(
        builder: (_) => PackageGalleryFullscreenViewer(
          photos: widget.photos,
          initialIndex: initialIndex,
          title: widget.title.isNotEmpty ? widget.title : widget.destination,
        ),
      ),
    );
  }

  BorderRadius get _radius =>
      widget.borderRadius ?? BorderRadius.circular(AppRadii.large);

  Widget _buildLoadingPlaceholder() {
    return Container(
      color: InkWashColors.paleBlue,
      alignment: Alignment.center,
      child: const SizedBox(
        width: 24,
        height: 24,
        child: CircularProgressIndicator(strokeWidth: 2),
      ),
    );
  }

  Widget _buildErrorFallback(String url) {
    return Container(
      color: InkWashColors.paleBlue,
      alignment: Alignment.center,
      padding: const EdgeInsets.symmetric(horizontal: AppSpacing.sm),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Icon(
            Icons.broken_image_outlined,
            color: InkWashColors.blueGrey,
            size: 38,
          ),
          const SizedBox(height: 6),
          Text(
            widget.title.isNotEmpty ? widget.title : 'Image unavailable',
            maxLines: 1,
            overflow: TextOverflow.ellipsis,
            textAlign: TextAlign.center,
            style: const TextStyle(
              color: InkWashColors.mutedInk,
              fontWeight: FontWeight.w600,
              fontSize: 12,
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final photos = widget.photos;

    // Case 1: No valid images available -> Fall back to standard TravelPlaceImage
    if (photos.isEmpty) {
      return TravelPlaceImage(
        place: {
          'title': widget.title.isNotEmpty ? widget.title : widget.destination,
          'imageUrl': widget.fallbackHeroUrl ?? '',
          'category': 'Travel package',
        },
        height: widget.height,
        width: double.infinity,
        borderRadius: _radius,
      );
    }

    // Case 2: Exactly 1 photo (Cover only) -> Render cover image without gallery controls
    if (photos.length == 1) {
      final singleUrl = photos.first;
      return ClipRRect(
        borderRadius: _radius,
        child: SizedBox(
          height: widget.height,
          width: double.infinity,
          child: InkWell(
            key: const ValueKey('package-cover-image'),
            onTap: () => _openFullscreen(context, 0),
            child: Image.network(
              singleUrl,
              key: ValueKey('package-gallery-single-$singleUrl'),
              fit: BoxFit.cover,
              width: double.infinity,
              height: widget.height,
              loadingBuilder: (context, child, progress) =>
                  progress == null ? child : _buildLoadingPlaceholder(),
              errorBuilder: (context, error, stackTrace) =>
                  _buildErrorFallback(singleUrl),
            ),
          ),
        ),
      );
    }

    // Case 3: Multiple photos (Cover + Gallery) -> Horizontally swipeable carousel with counter
    final safeIndex = _currentIndex.clamp(0, photos.length - 1);

    return ClipRRect(
      borderRadius: _radius,
      child: SizedBox(
        height: widget.height,
        width: double.infinity,
        child: Stack(
          children: [
            // Swipeable PageView
            PageView.builder(
              key: const ValueKey('package-gallery-carousel'),
              controller: _controller,
              itemCount: photos.length,
              onPageChanged: (idx) {
                setState(() {
                  _currentIndex = idx;
                });
              },
              itemBuilder: (context, index) {
                final photoUrl = photos[index];
                return InkWell(
                  key: ValueKey('package-gallery-slide-$index'),
                  onTap: () => _openFullscreen(context, index),
                  child: Image.network(
                    photoUrl,
                    fit: BoxFit.cover,
                    width: double.infinity,
                    height: widget.height,
                    loadingBuilder: (context, child, progress) =>
                        progress == null ? child : _buildLoadingPlaceholder(),
                    errorBuilder: (context, error, stackTrace) =>
                        _buildErrorFallback(photoUrl),
                  ),
                );
              },
            ),

            // Photo counter badge (e.g. 1/4)
            Positioned(
              bottom: AppSpacing.sm,
              right: AppSpacing.sm,
              child: Container(
                key: const ValueKey('package-gallery-counter'),
                padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
                decoration: BoxDecoration(
                  color: Colors.black.withValues(alpha: 0.65),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(
                      Icons.photo_library_outlined,
                      size: 13,
                      color: Colors.white,
                    ),
                    const SizedBox(width: 4),
                    Text(
                      '${safeIndex + 1}/${photos.length}',
                      style: const TextStyle(
                        color: Colors.white,
                        fontSize: 12,
                        fontWeight: FontWeight.w700,
                        letterSpacing: 0.3,
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// Fullscreen interactive image viewer with pinch-to-zoom and swipe navigation.
class PackageGalleryFullscreenViewer extends StatefulWidget {
  final List<String> photos;
  final int initialIndex;
  final String title;

  const PackageGalleryFullscreenViewer({
    super.key,
    required this.photos,
    this.initialIndex = 0,
    this.title = '',
  });

  @override
  State<PackageGalleryFullscreenViewer> createState() =>
      _PackageGalleryFullscreenViewerState();
}

class _PackageGalleryFullscreenViewerState
    extends State<PackageGalleryFullscreenViewer> {
  late final PageController _pageController;
  late int _currentIndex;

  @override
  void initState() {
    super.initState();
    _currentIndex =
        widget.initialIndex.clamp(0, math.max(0, widget.photos.length - 1));
    _pageController = PageController(initialPage: _currentIndex);
  }

  @override
  void dispose() {
    _pageController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final total = widget.photos.length;

    return Scaffold(
      backgroundColor: Colors.black,
      body: SafeArea(
        child: Stack(
          children: [
            // Fullscreen PageView with InteractiveViewer for smooth pinch-to-zoom
            PageView.builder(
              key: const ValueKey('gallery-fullscreen-pageview'),
              controller: _pageController,
              itemCount: total,
              onPageChanged: (idx) {
                setState(() {
                  _currentIndex = idx;
                });
              },
              itemBuilder: (context, index) {
                final photoUrl = widget.photos[index];
                return InteractiveViewer(
                  key: ValueKey('gallery-fullscreen-zoom-$index'),
                  minScale: 0.8,
                  maxScale: 4.0,
                  clipBehavior: Clip.none,
                  child: Center(
                    child: Image.network(
                      photoUrl,
                      fit: BoxFit.contain,
                      loadingBuilder: (context, child, progress) {
                        if (progress == null) return child;
                        return const Center(
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: Colors.white70,
                          ),
                        );
                      },
                      errorBuilder: (context, error, stackTrace) {
                        return Center(
                          child: Column(
                            mainAxisSize: MainAxisSize.min,
                            children: const [
                              Icon(
                                Icons.broken_image_outlined,
                                color: Colors.white54,
                                size: 48,
                              ),
                              SizedBox(height: 8),
                              Text(
                                'Image unavailable',
                                style: TextStyle(
                                  color: Colors.white70,
                                  fontSize: 13,
                                ),
                              ),
                            ],
                          ),
                        );
                      },
                    ),
                  ),
                );
              },
            ),

            // Top overlay bar with Close button and Photo Counter
            Positioned(
              top: 0,
              left: 0,
              right: 0,
              child: Container(
                padding: const EdgeInsets.symmetric(
                  horizontal: AppSpacing.sm,
                  vertical: AppSpacing.xs,
                ),
                decoration: BoxDecoration(
                  gradient: LinearGradient(
                    begin: Alignment.topCenter,
                    end: Alignment.bottomCenter,
                    colors: [
                      Colors.black.withValues(alpha: 0.7),
                      Colors.transparent,
                    ],
                  ),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    IconButton(
                      key: const ValueKey('gallery-fullscreen-close'),
                      tooltip: 'Close gallery',
                      icon: const Icon(
                        Icons.close_rounded,
                        color: Colors.white,
                        size: 26,
                      ),
                      onPressed: () => Navigator.of(context).pop(),
                    ),
                    if (total > 1)
                      Text(
                        '${_currentIndex + 1} / $total',
                        key: const ValueKey('gallery-fullscreen-counter'),
                        style: const TextStyle(
                          color: Colors.white,
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                          letterSpacing: 0.5,
                        ),
                      )
                    else
                      const SizedBox.shrink(),
                    const SizedBox(width: 48), // Balances the close button width
                  ],
                ),
              ),
            ),

            // Bottom caption (title)
            if (widget.title.isNotEmpty)
              Positioned(
                bottom: 0,
                left: 0,
                right: 0,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: AppSpacing.md,
                    vertical: AppSpacing.sm,
                  ),
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.bottomCenter,
                      end: Alignment.topCenter,
                      colors: [
                        Colors.black.withValues(alpha: 0.7),
                        Colors.transparent,
                      ],
                    ),
                  ),
                  child: Text(
                    widget.title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    textAlign: TextAlign.center,
                    style: const TextStyle(
                      color: Colors.white70,
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
