"""Decode full songs stored as UnityFS ``Fwk.Sound.SplitAcbData``.

Each 33-song bundle ships its ACB split across ten TextAsset chunks that
the game recombines at load time by:

1. joining the chunks in ``_chunks`` order;
2. XOR-ing every byte with ``0x5A``.

This module mirrors that algorithm, validates the reconstructed ACB
header, and hands the file off to the existing ``process_acb`` flow
for vgmstream + FLAC transcoding. The reassembled ACB lives only in a
temporary directory and is not retained as an output artifact.

UnityPy is imported lazily so the existing ACB/USM discovery path
does not pay the dependency cost.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from extract_cri_media import (
    MediaError,
    sha256_file,
)


XOR_KEY = 0x5A
EXPECTED_ACB_MAGIC = b"@UTF"
EXPECTED_AFS_MARKER = b"AFS2"

_DEPENDENCY_DIR = Path(__file__).resolve().parents[1] / ".deps"
if _DEPENDENCY_DIR.is_dir():
    sys.path.insert(0, str(_DEPENDENCY_DIR))


def load_unitypy():
    """Lazy import of UnityPy so the rest of the script does not pay for it."""

    try:
        import UnityPy  # type: ignore
    except ImportError as error:
        raise MediaError(
            "UnityPy is required to decode UnityFS SplitAcbData bundles"
        ) from error
    return UnityPy


@dataclass
class SplitAcbChunk:
    path_id: int


@dataclass
class SplitAcbCandidate:
    source: Path
    sha256: str
    container: str
    cue_sheet: str
    chunks: list[SplitAcbChunk] = field(default_factory=list)


class ReassemblyError(Exception):
    """Raised when a SplitAcbData bundle cannot be reassembled safely."""

    def __init__(self, stage: str, message: str, detail: Optional[str] = None) -> None:
        super().__init__(f"{stage}: {message}")
        self.stage = stage
        self.message = message
        self.detail = detail


def _safe_payload(raw: Any) -> Optional[bytes]:
    """Recover the raw bytes of a UnityPy TextAsset payload.

    UnityPy surfaces payloads as ``bytes`` or, when the underlying data
    cannot be decoded as text, as a ``str`` containing surrogate-escape
    characters. Both forms must round-trip back to the original bytes.
    """

    if isinstance(raw, (bytes, bytearray)):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8", errors="surrogateescape")
    return None


def _find_split_acb(environment) -> Optional[tuple[Any, str]]:
    """Return ``(MonoBehaviour, container_path)`` for the SplitAcbData."""

    for container_path, obj in _iter_objects(environment):
        try:
            tree = obj.read_typetree()
        except Exception:
            continue
        if not isinstance(tree, dict):
            continue
        if "_chunks" in tree and "_cueSheetName" in tree:
            return obj, container_path
    return None


def _iter_objects(environment) -> Iterable[tuple[str, Any]]:
    for obj in environment.objects:
        container_path = ""
        try:
            container_path = getattr(obj, "container", None) or ""
            if not container_path and obj.path_id:
                container_path = str(obj.path_id)
        except Exception:
            container_path = str(getattr(obj, "path_id", ""))
        yield container_path, obj


def _read_chunks(monobehaviour: Any) -> tuple[str, list[SplitAcbChunk]]:
    tree = monobehaviour.read_typetree()
    cue_sheet = str(tree.get("_cueSheetName") or "").strip()
    chunk_refs = tree.get("_chunks") or []
    if not isinstance(chunk_refs, list):
        raise ReassemblyError("invalid_chunks", "_chunks must be an array")

    chunks: list[SplitAcbChunk] = []
    for ref in chunk_refs:
        if not isinstance(ref, dict):
            continue
        path_id = int(ref.get("m_PathID") or ref.get("path_id") or 0)
        if not path_id:
            continue
        chunks.append(SplitAcbChunk(path_id=path_id))
    return cue_sheet, chunks


def _resolve_chunk_payload(
    environment, chunk: SplitAcbChunk
) -> tuple[Optional[str], Optional[bytes]]:
    """Return ``(name, payload)`` for the TextAsset at ``chunk.path_id``.

    ``name`` is taken from the TextAsset's ``m_Name`` so the report can
    record what was actually combined. ``payload`` is the raw bytes.
    """

    for _, obj in _iter_objects(environment):
        if obj.path_id != chunk.path_id:
            continue
        try:
            data = obj.read()
        except Exception:
            continue
        if data.__class__.__name__ != "TextAsset":
            continue
        payload = _safe_payload(
            getattr(data, "m_Script", getattr(data, "script", b""))
        )
        name = getattr(data, "m_Name", "") or ""
        return name, payload
    return None, None


def discover_split_acb(bundles_dir: Path) -> list[SplitAcbCandidate]:
    """Find every UnityFS bundle containing a SplitAcbData MonoBehaviour."""

    if not bundles_dir.is_dir():
        return []

    UnityPy = load_unitypy()
    candidates: list[SplitAcbCandidate] = []
    bundle_paths: list[Path] = []
    for candidate in bundles_dir.rglob("*"):
        if not candidate.is_file():
            continue
        try:
            with candidate.open("rb") as stream:
                if stream.read(7) != b"UnityFS":
                    continue
        except OSError:
            continue
        bundle_paths.append(candidate)

    for bundle_path in sorted(bundle_paths):
        try:
            environment = UnityPy.load(str(bundle_path))
        except Exception as exc:
            continue
        located = _find_split_acb(environment)
        if not located:
            continue
        monobehaviour, container_path = located
        try:
            cue_sheet, chunks = _read_chunks(monobehaviour)
        except ReassemblyError:
            continue
        if not cue_sheet or not chunks:
            continue
        candidates.append(
            SplitAcbCandidate(
                source=bundle_path,
                sha256=sha256_file(bundle_path),
                container=container_path,
                cue_sheet=cue_sheet,
                chunks=chunks,
            )
        )
    return candidates


@dataclass
class ReassemblyResult:
    acb_path: Path
    chunks: list[dict[str, Any]]
    total_size: int


def reassemble_acb(
    candidate: SplitAcbCandidate, work_dir: Path
) -> ReassemblyResult:
    """Reassemble the SplitAcbData into a single ACB file.

    The returned path lives inside ``work_dir`` and is the only copy of
    the reconstructed ACB. Callers must delete ``work_dir`` afterwards.
    """

    work_dir.mkdir(parents=True, exist_ok=True)
    UnityPy = load_unitypy()

    try:
        environment = UnityPy.load(str(candidate.source))
    except Exception as exc:
        raise ReassemblyError(
            "load_failed", f"could not reopen bundle: {exc}"
        ) from exc

    resolved: list[tuple[SplitAcbChunk, str, bytes]] = []
    total_size = 0
    for chunk in candidate.chunks:
        name, payload = _resolve_chunk_payload(environment, chunk)
        if payload is None:
            raise ReassemblyError(
                "missing_chunk",
                f"chunk path_id={chunk.path_id} has no TextAsset payload",
                detail=str(chunk.path_id),
            )
        if not payload:
            raise ReassemblyError(
                "empty_chunk",
                f"chunk {name or str(chunk.path_id)} is empty",
                detail=str(chunk.path_id),
            )
        resolved.append((chunk, name, payload))
        total_size += len(payload)

    buffer = bytearray(total_size)
    offset = 0
    for _, _, payload in resolved:
        buffer[offset : offset + len(payload)] = payload
        offset += len(payload)

    for index in range(len(buffer)):
        buffer[index] ^= XOR_KEY

    if not buffer.startswith(EXPECTED_ACB_MAGIC):
        raise ReassemblyError(
            "invalid_magic",
            "reassembled ACB does not start with @UTF",
            detail=buffer[:4].hex(),
        )
    if EXPECTED_AFS_MARKER not in buffer:
        raise ReassemblyError(
            "missing_afs2",
            "reassembled ACB does not contain AFS2 marker",
        )

    output = work_dir / f"{candidate.cue_sheet}.acb"
    output.write_bytes(bytes(buffer))

    chunk_records = [
        {
            "path_id": chunk.path_id,
            "name": name,
            "size": len(payload),
        }
        for chunk, name, payload in resolved
    ]
    return ReassemblyResult(
        acb_path=output, chunks=chunk_records, total_size=total_size
    )


def _hash_reassembled(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def process_split_acb(
    candidate: SplitAcbCandidate,
    output_root: Path,
    work_root: Path,
    hca_key: int,
    vgmstream: Path,
    ffmpeg: Path,
    process_acb: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    """Reassemble the bundle and feed it through ``process_acb``."""

    digest_prefix = candidate.sha256[:8]
    work_dir = work_root / f"split_{candidate.cue_sheet}_{digest_prefix}"
    output_dir = output_root / "audio" / f"{candidate.cue_sheet}_{digest_prefix}"
    work_dir.mkdir(parents=True, exist_ok=True)
    output_dir.mkdir(parents=True, exist_ok=True)

    record: dict[str, Any] = {
        "kind": "audio_split_acb",
        "source": str(candidate.source),
        "sha256": candidate.sha256,
        "container": candidate.container,
        "cue_sheet_name": candidate.cue_sheet,
        "xor_key": f"0x{XOR_KEY:02X}",
        "chunk_count": len(candidate.chunks),
    }

    try:
        reassembly = reassemble_acb(candidate, work_dir)
    except ReassemblyError as error:
        record["ok"] = False
        record["error"] = {
            "stage": error.stage,
            "message": error.message,
        }
        if error.detail is not None:
            record["error"]["detail"] = error.detail
        shutil.rmtree(work_dir, ignore_errors=True)
        return record

    record["chunks"] = reassembly.chunks
    record["declared_size"] = reassembly.total_size
    record["reconstructed_size"] = reassembly.acb_path.stat().st_size
    record["reconstructed_sha256"] = _hash_reassembled(reassembly.acb_path)

    try:
        decode_result = process_acb(
            reassembly.acb_path,
            candidate.sha256,
            output_root,
            work_root,
            hca_key,
            vgmstream,
            ffmpeg,
        )
    except Exception as exc:  # pragma: no cover - matches existing pattern
        record["ok"] = False
        record["error"] = {
            "stage": "decode",
            "message": f"{type(exc).__name__}: {exc}",
        }
        shutil.rmtree(work_dir, ignore_errors=True)
        return record

    record["hca_key"] = hca_key
    record["source_format"] = decode_result.get("source_format")
    record["declared_stream_slots"] = decode_result.get("declared_stream_slots")
    record["decoded_streams"] = decode_result.get("decoded_streams")
    record["streams"] = decode_result.get("streams", [])
    record["ok"] = bool(decode_result.get("ok"))

    shutil.rmtree(work_dir, ignore_errors=True)
    return record


__all__ = [
    "ReassemblyError",
    "SplitAcbCandidate",
    "SplitAcbChunk",
    "XOR_KEY",
    "discover_split_acb",
    "process_split_acb",
    "reassemble_acb",
]
