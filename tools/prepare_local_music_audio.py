"""Apply pinned song audio to the existing local projection without rebuilding other data."""
from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.music_audio import build_music_audio, publish_music_audio
from tools.music_audio_inputs import read_music_audio_inputs
from tools.release_preflight import inspect_plan, load_plan


def main():
    plan = ROOT / 'config/release-inputs.json'
    if inspect_plan(plan, require_production=True)['status'] != 'passed':
        raise ValueError('Release inputs failed preflight')
    source = load_plan(plan)[0]
    report = read_music_audio_inputs(source, ROOT)
    if report is None:
        raise ValueError('No music audio inputs bound')
    build = build_music_audio(ROOT / source['masterRoot'], report, repo_root=ROOT)
    records = publish_music_audio(build, ROOT / 'site/public', ffmpeg=Path('/opt/homebrew/bin/ffmpeg'), ffprobe=Path('/opt/homebrew/bin/ffprobe'))
    for record in records:
        build.overlays[record.track_id]['audioUrl'] = record.target_url
    paths = [ROOT / 'site/src/data/generated/catalog.json', ROOT / 'site/public/data/catalog.json']
    paths.extend((ROOT / 'site/public/data/releases' / source['contentReleaseId']).glob('*/catalog.json'))
    for path in paths:
        if not path.is_file():
            continue
        catalog = json.loads(path.read_text())
        if catalog.get('release', {}).get('id') != source['contentReleaseId']:
            raise ValueError(f'Local catalog identity mismatch: {path}')
        for track in catalog['musicTracks']:
            track.update(build.overlays[track['id']])
        catalog['publicationPolicy']['music']['audioPlayback'] = bool(records)
        catalog['publicationPolicy']['music']['audioDownload'] = bool(records)
        temporary = path.with_suffix('.audio.tmp')
        temporary.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + '\n')
        temporary.replace(path)
    print(f'Prepared {len(records)} songs in {len(paths)} local catalogs')


if __name__ == '__main__':
    main()
