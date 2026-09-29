#!/usr/bin/env python3
"""Refresh the static AnonTokyo player guide data for production deployment."""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.anontokyo_projection import build_anontokyo_projection
from tools.anontokyo_player_guide import build_anontokyo_player_guide
from tools.anontokyo_private_preview import _stage_audio, _stage_media

MASTER_ROOT = REPO_ROOT / "input/global/decrypted/master-json"
CATALOG = REPO_ROOT / "output/anontokyo-catalog.json"
MEDIA_ROOT = REPO_ROOT / "input/global/exported-images/bundles"
MAP_CONFIG_ROOT = REPO_ROOT / "input/global/exported-content/mapconfig/textassets"
AUDIO_MANIFEST = REPO_ROOT / "output/anontokyo-audio/manifest.json"
OUT_DIR = REPO_ROOT / "site/src/data/anontokyo-player-guide"
PUBLIC_DIR = REPO_ROOT / "site/public"


def main() -> None:
    map_configs = sorted(MAP_CONFIG_ROOT.glob("*MapConfig_1.json"))
    if len(map_configs) != 1:
        raise RuntimeError(
            f"expected exactly one MapConfig_1.json, found {len(map_configs)}"
        )
    with tempfile.TemporaryDirectory() as temporary:
        temporary_root = Path(temporary)
        projection = temporary_root / "projection"
        guide = temporary_root / "player-guide"
        build_anontokyo_projection(
            master_root=MASTER_ROOT,
            catalog_path=CATALOG,
            output_root=projection,
            source_release_id="global-staging-static",
            map_config_path=map_configs[0],
        )
        build_anontokyo_player_guide(
            projection_root=projection,
            output_root=guide,
        )

        OUT_DIR.mkdir(parents=True, exist_ok=True)
        for source in guide.glob("*.json"):
            shutil.copy2(source, OUT_DIR / source.name)

        staged, staged_bytes = _stage_media(
            projection,
            guide,
            PUBLIC_DIR,
            MEDIA_ROOT,
        )
        print(f"Images staged before audio: {len(staged)} files")
        audio, _ = _stage_audio(
            AUDIO_MANIFEST,
            PUBLIC_DIR,
            staged_count=len(staged),
            staged_bytes=staged_bytes,
        )
        staged.extend(audio)
        manifest_path = PUBLIC_DIR / "anontokyo-media.json"
        manifest_path.write_text(
            json.dumps(staged, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        shutil.copy2(manifest_path, OUT_DIR / "anontokyo-media.json")

        print(f"Static data refreshed: {len(list(OUT_DIR.glob('*.json')))} JSON files")
        print(f"Media staged: {len(staged)} files")


if __name__ == "__main__":
    main()
