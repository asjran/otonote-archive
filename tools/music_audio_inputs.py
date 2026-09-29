"""Validate the release identity and bytes of a pinned song-audio report."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


def file_digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def read_music_audio_inputs(source: dict, root: Path) -> Path | None:
    binding = source.get('musicAudioInputs')
    if binding is None:
        return None
    if not isinstance(binding, dict) or not isinstance(binding.get('report'), str) or not re.fullmatch('[a-f0-9]{64}', str(binding.get('sha256', ''))):
        raise ValueError('invalid musicAudioInputs binding')
    report_path = (root / binding['report']).resolve()
    if not report_path.is_relative_to(root.resolve()):
        raise ValueError('audio report escapes repository')
    if file_digest(report_path) != binding['sha256']:
        raise ValueError('audio report digest mismatch')
    report = json.loads(report_path.read_text())
    if report.get('schemaVersion') != 1 or report.get('identity') != {k: source[k] for k in ('region', 'channel', 'contentReleaseId')} or report.get('complete') is not True:
        raise ValueError('audio report release identity or completeness mismatch')
    records = report.get('files')
    if not isinstance(records, list) or not records:
        raise ValueError('audio report has no records')
    cues = set()
    for record in records:
        cue = record.get('cue_sheet_name')
        if not isinstance(cue, str) or not cue or cue in cues or not record.get('ok') or len(record.get('streams', [])) != 1:
            raise ValueError('invalid or duplicate audio record')
        cues.add(cue)
        stream = record['streams'][0]
        path = (report_path.parent / stream['output']).resolve()
        if not path.is_relative_to(report_path.parent) or not path.is_file():
            raise ValueError('audio payload escapes input directory or is missing')
        if path.stat().st_size != stream['size'] or file_digest(path) != stream.get('sha256'):
            raise ValueError('audio payload digest/size mismatch')
    return report_path
