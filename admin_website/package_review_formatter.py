"""Safe, presentation-only text and package field helpers for Admin Package Review.

All outputs are plain Python data structures rendered through Jinja2's default
HTML auto-escaping. No raw HTML strings or `|safe` filters are ever emitted.
"""
import re


_HEADING_RE = re.compile(r"^#{1,6}\s+(.+?)\s*$")
_STANDALONE_BOLD_RE = re.compile(r"^\*\*([^*\n]+)\*\*\s*:?\s*$")
_BULLET_RE = re.compile(r"^\s*(?:[-*\u2022]|\d+[.)])\s+(.+?)\s*$")
_BOLD_SPAN_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_ACTIVITY_TIME_RE = re.compile(
    r"^(\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?(?:\s*(?:[-–—]|to)\s*\d{1,2}:\d{2}(?:\s*(?:AM|PM|am|pm))?)?)\s*[-:–—]\s*(.+)$"
)


def inline_segments(text):
    """Split text into safe `{text, bold}` segments without leaving raw `**` markers."""
    raw = str(text or "")
    if not raw:
        return []
    segments = []
    pos = 0
    for match in _BOLD_SPAN_RE.finditer(raw):
        if match.start() > pos:
            plain = raw[pos : match.start()].replace("**", "")
            if plain:
                segments.append({"text": plain, "bold": False})
        bold_text = match.group(1).strip()
        if bold_text:
            segments.append({"text": bold_text, "bold": True})
        pos = match.end()
    if pos < len(raw):
        tail = raw[pos:].replace("**", "")
        if tail:
            segments.append({"text": tail, "bold": False})
    if not segments:
        cleaned = raw.replace("**", "")
        if cleaned:
            segments.append({"text": cleaned, "bold": False})
    return segments


def format_structured_blocks(raw_text):
    """Convert plain or Markdown-like operator text into structured block dicts."""
    text = str(raw_text or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    if not text:
        return []

    chunks = re.split(r"\n\s*\n", text)
    blocks = []
    for chunk in chunks:
        lines = [line.strip() for line in chunk.split("\n") if line.strip()]
        if not lines:
            continue

        # Flush contiguous bullets and paragraphs safely within each chunk
        pending_lines = []
        pending_bullets = []

        def flush_lines():
            if pending_lines:
                joined = " ".join(pending_lines)
                segs = inline_segments(joined)
                if segs:
                    blocks.append({"type": "paragraph", "segments": segs})
                pending_lines.clear()

        def flush_bullets():
            if pending_bullets:
                blocks.append({"type": "list", "items": list(pending_bullets)})
                pending_bullets.clear()

        for line in lines:
            heading_match = _HEADING_RE.match(line)
            if heading_match:
                flush_lines()
                flush_bullets()
                segs = inline_segments(heading_match.group(1))
                if segs:
                    blocks.append({"type": "heading", "segments": segs})
                continue

            bold_heading_match = _STANDALONE_BOLD_RE.match(line)
            if bold_heading_match and len(lines) > 1:
                flush_lines()
                flush_bullets()
                blocks.append({
                    "type": "heading",
                    "segments": [{"text": bold_heading_match.group(1).strip(), "bold": True}],
                })
                continue

            bullet_match = _BULLET_RE.match(line)
            if bullet_match:
                flush_lines()
                segs = inline_segments(bullet_match.group(1))
                if segs:
                    pending_bullets.append(segs)
                continue

            flush_bullets()
            pending_lines.append(line)

        flush_lines()
        flush_bullets()

    return blocks


def parse_itinerary_activity(raw_activity):
    """Normalise a string or dict itinerary activity without inventing times."""
    if isinstance(raw_activity, dict):
        name = str(
            raw_activity.get("activityName")
            or raw_activity.get("title")
            or raw_activity.get("name")
            or ""
        ).strip()
        time = str(
            raw_activity.get("scheduledTime")
            or raw_activity.get("timeSlot")
            or raw_activity.get("time")
            or ""
        ).strip()
        location = str(
            raw_activity.get("location") or raw_activity.get("address") or ""
        ).strip()
        description = str(raw_activity.get("description") or "").strip()
        if not time and name:
            match = _ACTIVITY_TIME_RE.match(name)
            if match:
                time = match.group(1).strip()
                name = match.group(2).strip()
        return {
            "time": time,
            "title": name or "Scheduled activity",
            "location": location,
            "description": description,
        }

    text = str(raw_activity or "").strip()
    if not text:
        return {"time": "", "title": "", "location": "", "description": ""}
    match = _ACTIVITY_TIME_RE.match(text)
    if match:
        return {
            "time": match.group(1).strip(),
            "title": match.group(2).strip(),
            "location": "",
            "description": "",
        }
    return {"time": "", "title": text, "location": "", "description": ""}


def parse_float(value):
    """Safely parse numeric prices without crashing on empty strings or None."""
    if value in (None, "") or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def register_package_review_filters(app):
    """Register presentation-only Jinja filters on the Flask admin app."""
    app.jinja_env.filters["structured_blocks"] = format_structured_blocks
    app.jinja_env.filters["inline_segments"] = inline_segments
    app.jinja_env.filters["parse_activity"] = parse_itinerary_activity
    app.jinja_env.filters["parse_float"] = parse_float
