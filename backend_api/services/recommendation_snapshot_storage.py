"""Lossless storage for ranked JSON results that exceed Firestore field constraints."""
import gzip
import json
from zlib import error as ZlibError

from google.api_core.exceptions import DataLoss, InvalidArgument


_FORMAT = 'json_gzip_v1'
_PART_BYTES = 512 * 1024
_MAX_PARTS = 16  # Leave room under Firestore's 10 MiB atomic commit limit.
_PAYLOAD = 'recommendationPayload'
_PART_COUNT = 'recommendationPayloadParts'
_FORMAT_FIELD = 'recommendationPayloadFormat'
_PARTS_COLLECTION = 'payload_parts'


def _validate_json_keys(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise TypeError('Non-string JSON key')
        for item in value.values():
            _validate_json_keys(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_json_keys(item)


def write_snapshot(db, ref, record):
    """Commit the ranked list and its generation header together."""
    results = record['recommendationResults']
    try:
        _validate_json_keys(results)
        encoded = json.dumps(results, ensure_ascii=False, allow_nan=False,
                             separators=(',', ':')).encode('utf-8')
    except (TypeError, ValueError, RecursionError):
        raise InvalidArgument('snapshot_non_json_metadata') from None
    payload = gzip.compress(encoded, compresslevel=6, mtime=0)
    if len(payload) > _PART_BYTES * _MAX_PARTS:
        error = InvalidArgument('snapshot_commit_size')
        error.snapshot_bytes = len(payload)
        raise error
    header = {key: value for key, value in record.items() if key != 'recommendationResults'}
    header[_FORMAT_FIELD] = _FORMAT
    try:
        if len(payload) <= _PART_BYTES:
            ref.set({**header, _PAYLOAD: payload})
            return
        parts = [payload[i:i + _PART_BYTES] for i in range(0, len(payload), _PART_BYTES)]
        batch = db.batch()
        batch.set(ref, {**header, _PART_COUNT: len(parts)})
        for index, part in enumerate(parts):
            batch.set(ref.collection(_PARTS_COLLECTION).document(str(index)), {_PAYLOAD: part})
        batch.commit()
    except InvalidArgument as error:
        error.snapshot_bytes = len(payload)
        raise


def load_snapshot(ref, record):
    """Return the same application record for legacy and encoded generations."""
    if _FORMAT_FIELD not in record:
        return record
    if record[_FORMAT_FIELD] != _FORMAT:
        raise DataLoss('Unknown recommendation snapshot format')
    try:
        if _PART_COUNT in record:
            count = record[_PART_COUNT]
            if type(count) is not int or not 2 <= count <= _MAX_PARTS:
                raise ValueError
            parts = ref.collection(_PARTS_COLLECTION)
            payload = b''.join(parts.document(str(index)).get().to_dict()[_PAYLOAD]
                               for index in range(count))
        else:
            payload = record[_PAYLOAD]
        results = json.loads(gzip.decompress(payload))
        if not isinstance(results, list) or not all(isinstance(item, dict) for item in results):
            raise ValueError
    except (TypeError, ValueError, KeyError, OSError, EOFError, ZlibError):
        raise DataLoss('Invalid recommendation snapshot payload') from None
    return {**{key: value for key, value in record.items()
               if key not in {_FORMAT_FIELD, _PART_COUNT, _PAYLOAD}},
            'recommendationResults': results}


def validation_reason(error):
    """Translate server errors to fixed codes. Never return the provider text."""
    message = error.message.lower()
    patterns = (
        ('snapshot_non_json_metadata', 'non_json_metadata'),
        ('snapshot_commit_size', 'commit_size'),
        ('maximum entity size', 'document_size'),
        ('document size', 'document_size'),
        ('maximum size', 'size_limit'),
        ('index entr', 'index_limit'),
        ('reserved', 'reserved_field'),
        ('field name', 'field_name'),
        ('nested', 'nested_value'),
        ('depth', 'nested_depth'),
    )
    return next((reason for fragment, reason in patterns if fragment in message),
                'firestore_invalid_argument')
