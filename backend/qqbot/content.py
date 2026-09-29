"""Read immutable bot bundles, independent of QQ and the site runtime."""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path


DATA_FILES = ("catalog.json", "card-detail-projections.json", "global-systems.json")


class ContentError(ValueError):
    pass


def inside(root: Path, relative: str) -> Path:
    path = (root / relative).resolve()
    if not path.is_relative_to(root.resolve()):
        raise ContentError("content path escapes bundle")
    return path


def validate_identity(catalog: dict, systems: dict, expected: str) -> None:
    release = catalog.get("release", {})
    context = catalog.get("projectionContext", {})
    if (release.get("id") != expected or context.get("contentReleaseId") != expected
            or systems.get("sourceReleaseId") != expected
            or release.get("region") != "global" or release.get("channel") != "production"
            or context.get("region") != "global" or context.get("channel") != "production"
            or context.get("locale") != "zh-CN"):
        raise ContentError("bundle requires one Global production Chinese release")


class Content:
    def __init__(self, root: Path, *, asset_loader=None):
        self.root = root.resolve()
        try:
            manifest = json.loads((self.root / "manifest.json").read_text())
            self.manifest, self.asset_loader = manifest, asset_loader
            if manifest["schemaVersion"] not in (1, 2):
                raise ContentError("unsupported bundle version")
            self.release_id = manifest["releaseId"]
            if not re.fullmatch(r"global-prod-[a-z0-9-]+", self.release_id):
                raise ContentError("invalid release id")
            files = manifest["files"]
            for name in DATA_FILES:
                if name not in files:
                    raise ContentError("missing data descriptor")
            for name, digest in files.items():
                if hashlib.sha256(inside(self.root, name).read_bytes()).hexdigest() != digest:
                    raise ContentError("bundle integrity check failed")
            self.catalog, self.details, self.systems = (
                json.loads(inside(self.root, name).read_text()) for name in DATA_FILES
            )
            validate_identity(self.catalog, self.systems, self.release_id)
            for dataset in ("characters", "bands", "memberCards", "supportCards", "musicTracks", "musicCharts", "assets"):
                rows = self.catalog[dataset]
                if not isinstance(rows, list) or not all(isinstance(row, dict) and "id" in row for row in rows):
                    raise ContentError("invalid catalog collection")
                if len({row["id"] for row in rows}) != len(rows):
                    raise ContentError("duplicate content identity")
            for dataset in ("memberCards", "supportCards"):
                expected_ids = {row["id"] for row in self.catalog[dataset]}
                detail_ids = [row["cardId"] for row in self.details[dataset]]
                if len(set(detail_ids)) != len(detail_ids) or not set(detail_ids) <= expected_ids:
                    raise ContentError("card details do not match catalog")
            for row in self.systems["gachaPools"]:
                if not isinstance(row, dict) or "id" not in row:
                    raise ContentError("invalid gacha collection")
            self.images = {}
            for asset_id, name in manifest["images"].items():
                if name not in files:
                    raise ContentError("unverified image")
                self.images[asset_id] = inside(self.root, name)
            if manifest["schemaVersion"] == 2:
                for identifier, item in manifest["remoteAssets"].items():
                    if (not re.fullmatch(r"asset-[a-z0-9-]+", identifier)
                            or not re.fullmatch(r"[0-9a-f]{64}", item["sha256"])
                            or item["suffix"] not in (".png", ".webp", ".jpg", ".jpeg")):
                        raise ContentError("invalid remote asset")
            self.snapshot = manifest["snapshotDate"]
            database = json.loads((self.root / "game-database.json").read_text()) if "game-database.json" in files else {}
            if database and database.get("sourceReleaseId") != self.release_id:
                raise ContentError("skill database release mismatch")
            self.skills = {s["id"]: s for s in database.get("skills", [])}
            self.characters = {x["id"]: x for x in self.catalog["characters"]}
            self.bands = {x["id"]: x for x in self.catalog["bands"]}
            self.cards = {x["masterId"]: x for x in self.catalog["memberCards"]}
            self.card_details = {x["cardId"]: x for key in ("memberCards", "supportCards")
                                 for x in self.details[key]}
        except (OSError, KeyError, TypeError, AttributeError, json.JSONDecodeError) as exc:
            raise ContentError("invalid or incomplete bot bundle") from exc

    def image(self, asset_id: str | None) -> Path | None:
        return self.asset_loader(asset_id) if self.asset_loader and asset_id else self.images.get(asset_id)

    def banner(self, pool: dict) -> Path | None:
        name = pool.get("bannerAssetName")
        if not name:
            return None
        for asset in self.catalog["assets"]:
            container = asset.get("containerPath", "")
            if container.endswith(f"/{name}.png"):
                return self.image(asset["id"])
        return None
