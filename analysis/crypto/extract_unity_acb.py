"""Extract CRI ACB payloads embedded in Unity ``CriAtomAcbAsset`` objects."""

from __future__ import annotations

import hashlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping


EXPECTED_ACB_MAGIC = b"@UTF"
EXPECTED_AFS_MARKER = b"AFS2"
MONOSCRIPT_BUNDLE_HASH = "e457eefe183530a5012c1afef0c94914"

for dependency_dir in (
    Path(__file__).resolve().parents[1] / "vendor",
    Path(__file__).resolve().parents[1] / ".deps",
):
    if dependency_dir.is_dir():
        sys.path.insert(0, str(dependency_dir))


@dataclass(frozen=True)
class UnityAcbCandidate:
    source: Path
    sha256: str
    container: str
    cue_sheet: str
    payload: bytes


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_unityfs_files(root: Path) -> list[Path]:
    """Return recursively cached UnityFS files, including extensionless files."""

    if not root.is_dir():
        return []
    matches: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                if stream.read(8) == b"UnityFS\x00":
                    matches.append(path)
        except OSError:
            continue
    return sorted(matches)


def serialized_acb_payload(tree: Mapping[str, Any]) -> bytes | None:
    """Read the payload used by ``CriSerializedBytesAssetImpl`` safely."""

    references = tree.get("references")
    if not isinstance(references, Mapping):
        return None
    ref_ids = references.get("RefIds")
    if not isinstance(ref_ids, list):
        return None
    for reference in ref_ids:
        if not isinstance(reference, Mapping):
            continue
        type_info = reference.get("type")
        if not isinstance(type_info, Mapping):
            continue
        if type_info.get("class") != "CriSerializedBytesAssetImpl":
            continue
        data = reference.get("data")
        values = data.get("data") if isinstance(data, Mapping) else None
        if not isinstance(values, list):
            continue
        try:
            payload = bytes(values)
        except (TypeError, ValueError):
            continue
        if payload.startswith(EXPECTED_ACB_MAGIC) and EXPECTED_AFS_MARKER in payload:
            return payload
    return None


def _find_monoscript_bundle(root: Path) -> Path | None:
    matches = sorted(root.glob(f"*/{MONOSCRIPT_BUNDLE_HASH}/__data"))
    return matches[0] if matches else None


def _iter_main_objects(environment: Any) -> Iterable[Any]:
    for obj in environment.objects:
        if obj.type.name == "MonoBehaviour":
            yield obj


def discover_unity_acb(
    bundles_dir: Path,
    *,
    script_bundle: Path | None = None,
) -> list[UnityAcbCandidate]:
    """Find every embedded ACB while allowing unrelated Unity objects to fail."""

    try:
        import UnityPy  # type: ignore
    except ImportError as error:  # pragma: no cover - environment guard
        raise RuntimeError("UnityPy is required to extract embedded CRI ACB") from error

    dependency = script_bundle or _find_monoscript_bundle(bundles_dir)
    candidates: list[UnityAcbCandidate] = []
    for index, bundle in enumerate(find_unityfs_files(bundles_dir), start=1):
        try:
            environment = UnityPy.load(str(bundle))
            if dependency and dependency != bundle:
                environment.load_file(str(dependency), is_dependency=True)
        except Exception:
            continue
        for obj in _iter_main_objects(environment):
            try:
                tree = obj.read_typetree()
                payload = serialized_acb_payload(tree)
                if payload is None:
                    continue
                cue_sheet = str(tree.get("m_Name") or "embedded_acb").strip()
                container = str(getattr(obj, "container", "") or "")
                candidates.append(
                    UnityAcbCandidate(
                        source=bundle,
                        sha256=_sha256(bundle),
                        container=container,
                        cue_sheet=cue_sheet,
                        payload=payload,
                    )
                )
            except Exception:
                continue
        if index % 500 == 0:
            print(
                f"scanned {index} UnityFS bundles; "
                f"{len(candidates)} embedded ACB assets",
                flush=True,
            )
    return candidates


def process_unity_acb(
    candidate: UnityAcbCandidate,
    output_root: Path,
    work_root: Path,
    hca_key: int,
    vgmstream: Path,
    ffmpeg: Path,
    process_acb: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Decode an embedded ACB through the shared validated CRI pipeline."""

    work_dir = work_root / f"unity_{candidate.cue_sheet}_{candidate.sha256[:8]}"
    work_dir.mkdir(parents=True, exist_ok=True)
    acb = work_dir / f"{candidate.cue_sheet}.acb"
    acb.write_bytes(candidate.payload)
    record: dict[str, Any] = {
        "kind": "audio_unity_acb",
        "source": str(candidate.source),
        "sha256": candidate.sha256,
        "container": candidate.container,
        "cue_sheet_name": candidate.cue_sheet,
        "embedded_size": len(candidate.payload),
    }
    try:
        decoded = process_acb(
            acb,
            candidate.sha256,
            output_root,
            work_root,
            hca_key,
            vgmstream,
            ffmpeg,
        )
        for key in (
            "hca_key",
            "source_format",
            "declared_stream_slots",
            "decoded_streams",
            "streams",
            "ok",
        ):
            record[key] = decoded.get(key)
    except Exception as error:
        record["ok"] = False
        record["error"] = {
            "stage": "decode",
            "message": f"{type(error).__name__}: {error}",
        }
    finally:
        shutil.rmtree(work_dir, ignore_errors=True)
    return record


__all__ = [
    "UnityAcbCandidate",
    "discover_unity_acb",
    "find_unityfs_files",
    "process_unity_acb",
    "serialized_acb_payload",
]
