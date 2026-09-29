"""Verify that the local development projection is the selected Global release."""
from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from tools.release_preflight import PreflightError, inspect_plan, load_plan
from tools.gallery import project_gallery
from tools.refresh_card_details import refresh_card_details
from tools.band_items import build_band_items
from tools.bgm_catalog import main as prepare_bgm


def main() -> None:
    plan_path = ROOT / "config/release-inputs.json"
    readiness = inspect_plan(plan_path, require_production=True)
    if readiness["status"] != "passed":
        raise PreflightError("Global production inputs are not ready")
    source = load_plan(plan_path)[0]
    catalog_path = ROOT / "site/src/data/generated/catalog.json"
    if not catalog_path.is_file():
        raise PreflightError("Global local projection is missing")
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    release = catalog.get("release", {})
    if release.get("id") != source["contentReleaseId"] or release.get("region") != "global":
        raise PreflightError("Local projection is not the selected Global production release")

    refresh_card_details(ROOT, source, catalog)

    band_items = build_band_items(
        ROOT / source["masterRoot"], source["contentReleaseId"], catalog["assets"]
    ).database
    band_payload = json.dumps(band_items, ensure_ascii=False, indent=2) + "\n"
    for base in (ROOT / "site/src/data/generated", ROOT / "site/public/data"):
        path = base / "band-items.json"
        if not path.exists() or path.read_text(encoding="utf-8") != band_payload:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(band_payload, encoding="utf-8")

    locale = catalog.get("projectionContext", {}).get("locale", "zh-CN")
    gallery = project_gallery(ROOT / source["masterRoot"], source["contentReleaseId"], locale)
    payload = json.dumps(gallery, ensure_ascii=False, indent=2) + "\n"
    for path in (ROOT / "site/src/data/generated/gallery.json", ROOT / "site/public/data/gallery.json"):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    prepare_bgm()


if __name__ == "__main__":
    main()
