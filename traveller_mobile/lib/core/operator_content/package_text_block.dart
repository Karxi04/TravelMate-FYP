import 'package:flutter/material.dart';

/// A compact preview that retains the complete operator text on demand.
class PackageTextBlock extends StatefulWidget {
  final String text;
  final String? preview;
  final TextStyle? style;
  final int collapsedLines;
  final String expandLabel;
  const PackageTextBlock(
      {super.key,
      required this.text,
      this.preview,
      this.style,
      this.collapsedLines = 4,
      this.expandLabel = 'Read more'});
  @override
  State<PackageTextBlock> createState() => _PackageTextBlockState();
}

class _PackageTextBlockState extends State<PackageTextBlock> {
  bool expanded = false;
  @override
  void didUpdateWidget(covariant PackageTextBlock oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.text != widget.text) expanded = false;
  }

  @override
  Widget build(BuildContext context) =>
      LayoutBuilder(builder: (context, constraints) {
        final style = widget.style ??
            Theme.of(context).textTheme.bodyMedium?.copyWith(height: 1.5);
        final preview = widget.preview ?? widget.text;
        final painter = TextPainter(
            text: TextSpan(text: preview, style: style),
            textDirection: Directionality.of(context),
            textScaler: MediaQuery.textScalerOf(context),
            maxLines: widget.collapsedLines)
          ..layout(maxWidth: constraints.maxWidth);
        final canExpand = preview != widget.text || painter.didExceedMaxLines;
        painter.dispose();
        return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              Text(expanded ? widget.text : preview,
                  style: style,
                  softWrap: true,
                  maxLines: expanded ? null : widget.collapsedLines,
                  overflow:
                      expanded ? TextOverflow.visible : TextOverflow.ellipsis),
              if (canExpand)
                Align(
                    alignment: Alignment.centerLeft,
                    child: TextButton(
                        onPressed: () => setState(() => expanded = !expanded),
                        child:
                            Text(expanded ? 'Show less' : widget.expandLabel))),
            ]);
      });
}
