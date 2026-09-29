"""Download one catalog-pinned Global asset from the public production patch host."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.release_preflight import digest
from tools.resource_pipeline.catalog_adapter import CatalogAdapter
from tools.resource_pipeline.transport import HttpRequest, HttpTransport


CATALOG = ROOT / "input/global/device-files/2026-09-24-v1.0.1-25/RemoteCatalog/catalog_main.bin"
CATALOG_SHA256 = "39b5d81ff337bfe0ef0af668f5b473a18e20aa1f8ce6d1c18ca4d6ffe0583c65"
HOST = "l14-prod-hk-patch-sirius.gamerfusiontech.com"
ROOT_PATTERN = re.compile(r"^https://l14-prod-hk-patch-sirius\.gamerfusiontech\.com/prod/hk_[a-f0-9]{32}")


def public_root() -> str:
    sources = json.loads((ROOT / "config/release-inputs.json").read_text(encoding="utf-8"))["environments"]
    source = next(entry for entry in sources if entry["id"] == "global-production")
    master = ROOT / source["masterRoot"] / "MasterRecommendContent.json"
    rows = json.loads(master.read_text(encoding="utf-8"))["_allData"]
    roots = {match.group(0) for row in rows
             if (match := ROOT_PATTERN.match(str(row.get("_bannerAsset", ""))))}
    if len(roots) != 1:
        raise ValueError("production Master does not identify one public patch root")
    return roots.pop()


def md5_digest(path: Path) -> str:
    value = hashlib.md5()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(chunk)
    return value.hexdigest()


def download(bundle: str, output: Path) -> dict:
    if not re.fullmatch(r"[a-z0-9_-]+\.bundle", bundle):
        raise ValueError("bundle must be an exact catalog bundle name")
    if output.exists() or output.is_symlink() or output.with_suffix(output.suffix + ".json").exists():
        raise ValueError("output already exists")
    if digest(CATALOG) != CATALOG_SHA256:
        raise ValueError("captured catalog digest mismatch")
    matches = [location for location in CatalogAdapter().parse(CATALOG).locations
               if location.primary_key == bundle and location.provider_id.endswith((".AssetBundleCryptProvider", ".AssetBundleProvider"))]
    if len(matches) != 1:
        raise ValueError("bundle is not unique in the asset catalog")
    location = matches[0]
    parsed = urlsplit(location.internal_id)
    if parsed.scheme != "https" or parsed.hostname != "dummy.net" or parsed.path != f"/asset/Android/{bundle}":
        raise ValueError("bundle catalog path is not the expected Android asset path")
    if not isinstance(location.expected_size, int) or location.expected_size <= 0:
        raise ValueError("catalog has no positive expected bundle size")
    url = f"{public_root()}{parsed.path}"
    transport = HttpTransport(allowed_hosts=(HOST,), connect_timeout_seconds=20,
                              read_timeout_seconds=60, max_response_bytes=location.expected_size)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f".{output.name}-", dir=output.parent) as temporary:
        part = Path(temporary) / "download.part"
        with part.open("wb") as stream:
            receipt = transport.download(HttpRequest("GET", url), stream)
        if receipt.status != 200 or receipt.byte_size != location.expected_size:
            raise ValueError("public patch response size differs from the pinned catalog")
        if location.provider_id.endswith(".AssetBundleProvider"):
            with part.open("rb") as data:
                if data.read(7) != b"UnityFS":
                    raise ValueError("plain asset bundle has no UnityFS header")
        sha = digest(part)
        etag = receipt.headers.get("etag", "").strip('"')
        if re.fullmatch(r"[a-fA-F0-9]{32}", etag) and md5_digest(part) != etag.lower():
            raise ValueError("public patch ETag differs from the downloaded bytes")
        report = {"catalogSha256": CATALOG_SHA256, "bundle": bundle, "url": url,
                  "byteSize": receipt.byte_size, "sha256": sha, "etag": etag or None,
                  "catalogHashAlgorithm": location.expected_hash_algorithm,
                  "catalogHash": location.expected_hash}
        report_path = output.with_suffix(output.suffix + ".json")
        part.rename(output)
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(download(args.bundle, args.output), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
