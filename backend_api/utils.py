from datetime import datetime, timezone


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def doc_to_dict(doc):
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data
