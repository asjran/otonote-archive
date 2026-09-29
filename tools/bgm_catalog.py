"""Version-bound BGM projection and browser audio publication."""
from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.music_audio_inputs import file_digest

CATEGORIES = [
    ('home', '主界面', 'Home', '标题与主界面音乐', 'Title and home screen'),
    ('event', '活动', 'Events', '生日与活动场景音乐', 'Birthday and event scenes'),
    ('story', '剧情', 'Stories', '故事与留影日记音乐', 'Stories and snapshot diaries'),
    ('live', '演出', 'Live', '演出准备与结算音乐', 'Live preparation and results'),
    ('gacha', '招募', 'Recruitment', '招募界面与演出音乐', 'Recruitment screens and sequences'),
    ('other', '其他', 'Other', '环境与其他场景音乐', 'Ambience and other scenes'),
]
SCENES = {
    'timing_adjust': ('other', '判定时机校准', 'Timing calibration'),
    'sound_bgm_title': ('home', '标题画面', 'Title screen'),
    'sound_bgm_home': ('home', '主界面', 'Home screen'),
    'sound_bgm_birthday': ('event', '生日场景', 'Birthday'),
    'sound_bgm_livetop': ('live', '演出准备', 'Live preparation'),
    'sound_bgm_liveresult': ('live', '演出结算', 'Live results'),
    'sound_bgm_gachatop': ('gacha', '招募界面', 'Recruitment screen'),
    'sound_bgm_gacha': ('gacha', '招募演出', 'Recruitment sequence'),
    'sound_bgm_gacharesult': ('gacha', '招募结果', 'Recruitment results'),
    'sound_bgm_snapdiary_neutral': ('story', '留影日记 · 日常', 'Snapshot diary · Everyday'),
    'sound_bgm_snapdiary_positive': ('story', '留影日记 · 轻快', 'Snapshot diary · Positive'),
    'sound_bgm_snapdiary_negative': ('story', '留影日记 · 低落', 'Snapshot diary · Negative'),
}


def classify(cue: str, asset_path: str, locale: str) -> tuple[str, str, bool]:
    english = locale == 'en'
    if cue in SCENES:
        category, zh, en = SCENES[cue]
        return category, en if english else zh, True
    if cue.startswith('sound_bgm_') and cue.endswith('_offline'):
        band = cue.removeprefix('sound_bgm_').removesuffix('_offline').title()
        return 'other', f'{band} · ' + ('Offline scene' if english else '离线场景'), True
    if '/adv/bgm/' in asset_path.lower() or cue.startswith('sound_bgm_adv_'):
        title = cue.removeprefix('sound_bgm_adv_').replace('_', ' ').strip().title()
        return 'story', title, True
    if cue == 'spot_1_1' and 'ambientbgm' in asset_path.lower():
        return 'other', 'Scene ambience · 1-1' if english else '场景环境音 · 1-1', True
    return 'other', cue, False


def read_bgm_inputs(source: dict, root: Path) -> tuple[Path, dict] | None:
    binding = source.get('bgmAudioInputs')
    if binding is None:
        return None
    path = (root / binding['report']).resolve()
    if not path.is_relative_to(root.resolve()) or file_digest(path) != binding.get('sha256'):
        raise ValueError('BGM report path/digest mismatch')
    data = json.loads(path.read_text())
    if (data.get('schemaVersion') != 1 or data.get('complete') is not True
            or data.get('identity') != {key: source[key] for key in ('region', 'channel', 'contentReleaseId')}):
        raise ValueError('BGM report release/completeness mismatch')
    seen = set()
    if not data.get('files'):
        raise ValueError('BGM report is empty')
    for record in data['files']:
        cue = record.get('cue_sheet_name')
        if not cue or cue in seen or not record.get('ok') or not record.get('streams'):
            raise ValueError('Invalid or duplicate BGM record')
        seen.add(cue)
        for stream in record['streams']:
            file = (path.parent / stream['output']).resolve()
            if (not file.is_relative_to(path.parent) or not file.is_file()
                    or file.stat().st_size != stream['size'] or file_digest(file) != stream['sha256']
                    or not stream.get('validation', {}).get('ok') or stream['duration_seconds'] <= 0):
                raise ValueError('BGM stream integrity/validation mismatch')
    return path, data


def selected_streams(records):
    """Prefer dedicated cue sheets to copies in the shared Bgm sheet.

    Keep every subsong of the selected sheet, including same-named variants.
    """
    grouped = defaultdict(list)
    for record in records:
        for stream in record['streams']:
            cue = stream.get('name') or record['cue_sheet_name']
            grouped[cue].append((record, stream))
    for cue, versions in sorted(grouped.items()):
        dedicated = [pair for pair in versions if pair[0]['cue_sheet_name'].lower() == cue.lower()]
        yield cue, dedicated or versions


def publish_stream(stream, inputs: Path, public: Path) -> dict:
    """Content-address output, validate cached bytes, and encode once."""
    ffmpeg = shutil.which('ffmpeg') or '/opt/homebrew/bin/ffmpeg'
    source = (inputs / stream['output']).resolve()
    name = stream['sha256'][:24] + '.m4a'
    target = public / 'media/bgm' / name
    audit_path = public / 'media/bgm' / (name + '.json')
    target.parent.mkdir(parents=True, exist_ok=True)
    from tools.conversion_cache import restore as cache_restore, save as cache_save
    recipe = 'bgm-aac-192k-mp4-v1'
    if not target.exists() and cache_restore(stream['sha256'], recipe, target):
        audit_path.write_text(json.dumps({'sourceSha256': stream['sha256'], 'sha256': file_digest(target)}) + '\n')
    valid = False
    if target.exists() and audit_path.exists():
        audit = json.loads(audit_path.read_text())
        valid = audit.get('sourceSha256') == stream['sha256'] and audit.get('sha256') == file_digest(target)
    if not valid:
        with tempfile.TemporaryDirectory(prefix='.encode-', dir=target.parent) as temporary_dir:
            temporary = Path(temporary_dir) / 'audio.m4a'
            subprocess.run([ffmpeg, '-v', 'error', '-y', '-i', str(source), '-map', '0:a:0',
                            '-map_metadata', '-1', '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(temporary)], check=True)
            subprocess.run([ffmpeg, '-v', 'error', '-xerror', '-i', str(temporary), '-map', '0:a:0', '-f', 'null', '-'], check=True)
            temporary.replace(target)
        audit = {'sourceSha256': stream['sha256'], 'sha256': file_digest(target)}
        audit_path.write_text(json.dumps(audit) + '\n')
    cache_save(stream['sha256'], recipe, target)
    return {'url': '/media/bgm/' + name, 'format': 'M4A', 'byteSize': target.stat().st_size,
            'duration': round(stream['duration_seconds'], 3), 'sha256': audit['sha256']}


def project_bgm(source: dict, root: Path, public: Path, locale: str,
                *, inputs=None) -> dict:
    if inputs is None:
        inputs = read_bgm_inputs(source, root)
    tracks = []
    known = set()
    if inputs:
        report_path, report = inputs
        for cue, versions in selected_streams(report['files']):
            known.add(cue)
            for index, (record, stream) in enumerate(versions, 1):
                category, title, confirmed = classify(cue, record.get('assetPath', ''), locale)
                if len(versions) > 1:
                    title += f' · {"Part" if locale == "en" else "片段"} {index}'
                safe_cue = re.sub(r'[^a-zA-Z0-9_-]', '-', cue)
                identifier = f'bgm-{safe_cue}-{index}'
                audio = publish_stream(stream, report_path.parent, public)
                tracks.append({'id': identifier, 'cueName': cue, 'title': title, 'categoryIds': [category],
                               'classificationConfirmed': confirmed, 'status': 'available', 'audio': audio,
                               'downloadName': identifier + '.m4a', 'sourceAsset': record.get('assetPath', ''),
                               'cueSheet': record['cue_sheet_name']})
    master = root / source['masterRoot']
    sounds = json.loads((master / 'MasterSound.json').read_text())['_allData']
    for sound in sounds:
        cue = sound['_cueName']
        if not cue.startswith('sound_bgm_') or cue in known:
            continue
        known.add(cue)
        category, title, confirmed = classify(cue, '', locale)
        tracks.append({'id': f'bgm-{cue}-1', 'cueName': cue, 'title': title, 'categoryIds': [category],
                       'classificationConfirmed': confirmed, 'status': 'missing', 'audio': None,
                       'downloadName': '', 'sourceAsset': '', 'cueSheet': ''})
    order = {category[0]: index for index, category in enumerate(CATEGORIES)}
    tracks.sort(key=lambda t: (order[t['categoryIds'][0]], t['title'], t['id']))
    return {'schemaVersion': 1, 'sourceReleaseId': source['contentReleaseId'], 'locale': locale,
            'categories': [{'id': key, 'label': en if locale == 'en' else zh,
                            'description': en_desc if locale == 'en' else zh_desc}
                           for key, zh, en, zh_desc, en_desc in CATEGORIES], 'tracks': tracks}


def main():
    from tools.release_preflight import load_plan
    source = load_plan(ROOT / 'config/release-inputs.json')[0]
    catalog = json.loads((ROOT / 'site/src/data/generated/catalog.json').read_text())
    if catalog['release']['id'] != source['contentReleaseId']:
        raise ValueError('BGM local projection release mismatch')
    locale = catalog.get('projectionContext', {}).get('locale', 'zh-CN')
    payload = project_bgm(source, ROOT, ROOT / 'site/public', locale)
    destinations = [ROOT / 'site/src/data/generated', ROOT / 'site/public/data']
    for base in destinations[:]:
        versioned = base / 'releases' / source['contentReleaseId'] / locale
        if versioned.is_dir():
            destinations.append(versioned)
    for directory in destinations:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / 'bgm.json').write_text(json.dumps(payload, ensure_ascii=False, indent=2) + '\n')
    print(f'BGM: {len(payload["tracks"])} tracks, {sum(t["audio"] is not None for t in payload["tracks"])} playable')


if __name__ == '__main__':
    main()
