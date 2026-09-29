"""Publish Master-bound short song cues and their release-scoped UI manifest.

Run after import_global_music_audio.py --variant preview --output <directory>.
Full song audio remains in /media/music; this command never prunes that directory.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.music_audio import build_music_audio, publish_music_audio
from tools.music_audio_inputs import file_digest, read_music_audio_inputs
from tools.release_preflight import load_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = args.report.resolve()
    source = dict(next(x for x in load_plan(ROOT / 'config/release-inputs.json') if x['id'] == 'global-production'))
    source['musicAudioInputs'] = {'report': str(report.relative_to(ROOT)), 'sha256': file_digest(report)}
    read_music_audio_inputs(source, ROOT)
    build = build_music_audio(ROOT / source['masterRoot'], report, repo_root=ROOT, sound_field='_jingleSoundID')
    destination = ROOT / 'site/public/media/music-previews'
    destination.mkdir(parents=True, exist_ok=True)
    tracks = {}
    with tempfile.TemporaryDirectory(prefix='song-previews-') as temp:
        records = publish_music_audio(build, Path(temp), ffmpeg=Path('/opt/homebrew/bin/ffmpeg'), ffprobe=Path('/opt/homebrew/bin/ffprobe'))
        for record in records:
            filename = record.target_filename
            shutil.copy2(Path(temp) / 'media/music' / filename, destination / filename)
            tracks[record.track_id] = {'url': f'/media/music-previews/{filename}', 'duration': record.duration_seconds}
    manifest = {'contentReleaseId': source['contentReleaseId'], 'tracks': tracks}
    (ROOT / 'site/src/data/music-previews.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(f'Prepared {len(tracks)} original song previews')


if __name__ == '__main__':
    main()
