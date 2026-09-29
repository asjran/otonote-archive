"""Package the verified MyGO lobby export for the independent website viewer."""
from pathlib import Path
import argparse
import hashlib
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.crypto.decrypt_global_formal_scores import UnityPy  # loads the pinned image runtime
from PIL import Image


def prepare(source: Path, output: Path):
    source = source.resolve()
    scene = json.loads((source / 'scene.json').read_text())
    report = json.loads((source / 'report.json').read_text())
    capture = ROOT / 'input/global/device-files/2026-09-24-v1.0.1-25'
    for entry in report:
        raw = capture / entry['source']
        if hashlib.sha256(raw.read_bytes()).hexdigest() != entry['sha256']:
            raise ValueError(f"Changed capture: {entry['source']}")
    output.mkdir(parents=True, exist_ok=True)
    mesh_ids = {node['mesh'] for node in scene['nodes'] if 'mesh' in node}
    scene['meshes'] = {key: value for key, value in scene['meshes'].items() if key in mesh_ids}
    scene['calibration'] = {'backgroundPosition': [.378, -.116, -1.437], 'verticalFov': 30, 'referenceAspect': 16 / 9}
    (output / 'scene.json').write_text(json.dumps(scene, separators=(',', ':')))
    for name, target in [('001_mygo_02_lobby_0102_texture.png', 'background.webp'), ('01_mygo_02_lobby_01.png', 'characters.webp')]:
        Image.open(source / name).save(output / target, 'WEBP', lossless=True, method=6)
    atlas = (source / '01_mygo_02_lobby_01.atlas.txt').read_text().replace('01_mygo_02_lobby_01.png', 'characters.webp')
    (output / 'characters.atlas').write_text(atlas)
    for node in scene['nodes']:
        if 'spine' in node:
            data = json.loads((source / (node['spine'] + '.txt')).read_text())
            (output / (node['spine'] + '.json')).write_text(json.dumps(data, separators=(',', ':')))
    # Poster from the verified browser render, excluding the prototype toolbar.
    shot = Image.open(source / 'recreated-full.jpg')
    if shot.size != (1280, 720):
        raise ValueError('Unexpected verified screenshot dimensions')
    shot.crop((0, 69, 1280, 663)).save(output / 'poster.webp', 'WEBP', quality=88)
    files = [{'path': p.name, 'bytes': p.stat().st_size, 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
             for p in sorted(output.iterdir()) if p.is_file() and p.name != 'manifest.json']
    manifest = {'schemaVersion': 1, 'sceneId': 10007, 'contentReleaseId': 'global-prod-20260924-v1-0-1-25-39b5d81f',
                'sourceCapture': '2026-09-24-v1.0.1-25', 'scene': 'home_001_mygo_02_lobby_0102_01',
                'durationSeconds': 4, 'approximateCamera': True, 'files': files,
                'sources': [{'bundle': r['bundle'], 'sha256': r['sha256']} for r in report]}
    (output / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'files': len(files), 'totalBytes': sum(f['bytes'] for f in files), 'output': str(output)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=ROOT / 'output/verification/immersive-home-20260927')
    parser.add_argument('--output', type=Path, default=ROOT / 'site/public/immersive/mygo-lobby-v1')
    args = parser.parse_args()
    prepare(args.source, args.output)
