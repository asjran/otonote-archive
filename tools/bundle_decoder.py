"""Resolve bundle material from exact external version/metadata bindings.

Profiles contain FieldRef indices, never keys. Unknown metadata is rejected before
reading fields; runtime decoding never searches candidates or falls back to a
mapping from another client version.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct

PROFILE_ENV = 'OURNOTES_BUNDLE_DECODER_PROFILE'
_FIELDS = {'clientVersion', 'metadataSha256', 'keyFieldUsage', 'nonceSeedFieldUsage'}


def _profile_entries(path):
    try:
        raw = Path(path).read_bytes()
        if len(raw) > 262144: raise ValueError
        document = json.loads(raw)
        if (not isinstance(document, dict) or set(document) != {'schemaVersion', 'profiles'}
                or type(document['schemaVersion']) is not int or document['schemaVersion'] != 1
                or not isinstance(document['profiles'], list) or not document['profiles']):
            raise ValueError
        seen = set()
        for row in document['profiles']:
            if not isinstance(row, dict) or set(row) != _FIELDS: raise ValueError
            version, digest = row['clientVersion'], row['metadataSha256']
            if (not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._+-]{0,63}', version)
                    or not isinstance(digest, str) or not re.fullmatch('[a-f0-9]{64}', digest)):
                raise ValueError
            for name in ('keyFieldUsage', 'nonceSeedFieldUsage'):
                usage = row[name]
                if type(usage) is not int or not 0x80000001 <= usage <= 0x9FFFFFFF or usage & 0xE0000001 != 0x80000001:
                    raise ValueError
            if row['keyFieldUsage'] == row['nonceSeedFieldUsage']: raise ValueError
            binding = (version, digest)
            if binding in seen: raise ValueError
            seen.add(binding)
        return document['profiles']
    except (OSError, ValueError, TypeError, UnicodeError):
        raise ValueError('invalid bundle decoder profile') from None


def _binding(metadata, client_version, profile_path):
    path = profile_path if profile_path is not None else os.environ.get(PROFILE_ENV)
    if not path: raise ValueError('bundle decoder profile is required')
    rows = _profile_entries(path)
    identity = hashlib.sha256(metadata.data).hexdigest()
    selected = next((row for row in rows if row['clientVersion'] == client_version
                     and row['metadataSha256'] == identity), None)
    if selected is None: raise ValueError('unsupported bundle decoder binding')
    return selected


def resolve_bundle_decoder(metadata, client_version, *, profile_path=None):
    """Read one profile snapshot and bind the returned material to its receipt."""
    selected = _binding(metadata, client_version, profile_path)
    binding = hashlib.sha256(json.dumps(selected, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return (field_bytes(metadata, selected['keyFieldUsage'], 16),
            field_bytes(metadata, selected['nonceSeedFieldUsage'], 8), binding)


def bundle_material(metadata, client_version, *, profile_path=None):
    return resolve_bundle_decoder(metadata, client_version, profile_path=profile_path)[:2]


def field_bytes(metadata, usage: int, length: int) -> bytes:
    """Resolve an IL2CPP FieldRef usage to its FieldRVA default bytes."""
    index = (usage & 0x1FFFFFFF) >> 1
    refs_offset, _, refs_count = metadata.sections[22]
    if index >= refs_count:
        raise ValueError("FieldRef usage is outside metadata")
    type_index, local_field = struct.unpack_from("<II", metadata.data, refs_offset + index * 8)
    owners = [
        i for i in range(metadata.type_count)
        if struct.unpack_from("<I", metadata.data, metadata.type_offset + i * 82 + 8)[0] == type_index
    ]
    if len(owners) != 1 or metadata.type_name(owners[0]) != "<PrivateImplementationDetails>":
        raise ValueError("FieldRef owner is not the expected private implementation type")
    # v39 TypeDefinition fieldStart is at byte 26 in its 82-byte record.
    field_start = struct.unpack_from("<I", metadata.data, metadata.type_offset + owners[0] * 82 + 26)[0]
    field_index = field_start + local_field
    defaults_offset, _, defaults_count = metadata.sections[7]
    matches = [
        data_index
        for i in range(defaults_count)
        for current, _, data_index in (struct.unpack_from("<III", metadata.data, defaults_offset + i * 12),)
        if current == field_index
    ]
    if len(matches) != 1:
        raise ValueError("FieldRef has no unique default value")
    data_offset, data_size, _ = metadata.sections[8]
    if matches[0] + length > data_size:
        raise ValueError("FieldRef default value exceeds the data section")
    return metadata.data[data_offset + matches[0]:data_offset + matches[0] + length]

