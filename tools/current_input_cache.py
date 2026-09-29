"""Reuse verified sealed inputs without duplicating large unchanged media."""
from tools.global_remote_sync import file_hash
from tools.immutable_files import link_or_copy


def verified_link(source, target, expected):
    if not source.is_file() or file_hash(source) != expected:
        raise ValueError('cached input digest mismatch: ' + source.name)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if file_hash(target) != expected: raise ValueError('conflicting cached input: ' + target.name)
        return
    link_or_copy(source, target)
    if file_hash(target) != expected: raise ValueError('cached input changed during reuse')
