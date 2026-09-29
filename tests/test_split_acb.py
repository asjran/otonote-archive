from __future__ import annotations

import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "analysis" / ".deps"))
sys.path.insert(0, str(REPO_ROOT / "analysis" / "crypto"))

from extract_split_acb import (  # noqa: E402
    EXPECTED_ACB_MAGIC,
    EXPECTED_AFS_MARKER,
    ReassemblyError,
    SplitAcbCandidate,
    SplitAcbChunk,
    XOR_KEY,
    _safe_payload,
    reassemble_acb,
)


def _build_payload(text: str) -> bytes:
    """Synthesize the kind of surrogate-escape payload UnityPy returns."""

    return text.encode("utf-8", errors="surrogateescape")


def _expected_payload(text: str) -> bytes:
    """Recover the original bytes via the same surrogate-escape roundtrip."""

    return _safe_payload(_build_payload(text))


def _fake_environment(chunks: list[tuple[int, str, str]]):
    """Build a stub environment that mimics UnityPy's ``objects`` API.

    ``chunks`` is a list of ``(path_id, name, text)`` triples that the
    reassembler will combine.
    """

    class TextAsset:
        """Mimic UnityPy's TextAsset data type."""

        __slots__ = ("m_Name", "m_Script")

        def __init__(self, name: str, text: str) -> None:
            self.m_Name = name
            self.m_Script = text

    class _Object:
        __slots__ = ("path_id", "_asset")

        def __init__(self, path_id: int, asset: TextAsset) -> None:
            self.path_id = path_id
            self._asset = asset

        def read(self):
            return self._asset

        def read_typetree(self):
            return {}

    class _Env:
        def __init__(self) -> None:
            self.objects = []

    env = _Env()
    for path_id, name, text in chunks:
        env.objects.append(_Object(path_id, TextAsset(name, text)))
    return env


def _patch_environment(monkey_patcher, env) -> None:
    import extract_split_acb

    monkey_patcher.setattr(
        extract_split_acb, "load_unitypy", lambda: _StubUnityPy(env)
    )


class _StubUnityPy:
    def __init__(self, env) -> None:
        self._env = env

    def load(self, _bundle_path):  # pragma: no cover - never called in tests
        return self._env


class SafePayloadTest(unittest.TestCase):
    def test_roundtrip_surrogate_escape(self) -> None:
        raw = bytes(range(256))
        # Bytes >= 0x80 trigger surrogateescape when encoded via str().
        text = raw.decode("utf-8", errors="surrogateescape")
        self.assertEqual(_safe_payload(text), raw)

    def test_passthrough_for_bytes(self) -> None:
        self.assertEqual(_safe_payload(b"\x00\x01\x02"), b"\x00\x01\x02")

    def test_none_for_unknown(self) -> None:
        self.assertIsNone(_safe_payload(42))


class ReassembleAcbTest(unittest.TestCase):
    def setUp(self) -> None:
        import extract_split_acb

        self._original_load_unitypy = extract_split_acb.load_unitypy

    def tearDown(self) -> None:
        import extract_split_acb

        extract_split_acb.load_unitypy = self._original_load_unitypy

    def _patch(self, env) -> None:
        import extract_split_acb

        extract_split_acb.load_unitypy = lambda: _StubUnityPy(env)

    def test_assembles_two_chunks_in_declaration_order(self) -> None:
        # Build a 256-byte target that starts with @UTF and contains AFS2.
        expected = EXPECTED_ACB_MAGIC + b"AFS2" + b"\x00" * 248
        xor_target = bytes(b ^ XOR_KEY for b in expected)
        env = _fake_environment(
            [
                (1, "song-001", _build_payload(_expected_payload_text(xor_target[:128]))),
                (2, "song-002", _build_payload(_expected_payload_text(xor_target[128:]))),
            ]
        )
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[SplitAcbChunk(path_id=1), SplitAcbChunk(path_id=2)],
        )
        with _temp_workdir() as work_dir:
            result = reassemble_acb(candidate, work_dir)
            self.assertEqual(result.total_size, 256)
            self.assertEqual(len(result.chunks), 2)
            self.assertEqual(result.chunks[0]["name"], "song-001")
            self.assertEqual(result.chunks[1]["name"], "song-002")
            recovered = result.acb_path.read_bytes()
            self.assertEqual(recovered, expected)

    def test_xor_zero_key_round_trip(self) -> None:
        # The chunk payload in real bundles holds the post-XOR bytes; the
        # reassembler XORs them once more to recover the original ACB.
        expected = EXPECTED_ACB_MAGIC + b"AFS2" + b"\x00" * 60
        encoded = bytes(b ^ XOR_KEY for b in expected)
        env = _fake_environment(
            [(1, "song-001", _build_payload(_expected_payload_text(encoded)))]
        )
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[SplitAcbChunk(path_id=1)],
        )
        with _temp_workdir() as work_dir:
            result = reassemble_acb(candidate, work_dir)
            recovered = result.acb_path.read_bytes()
            self.assertEqual(recovered, expected)

    def test_magic_and_afs2_are_validated(self) -> None:
        env = _fake_environment(
            [
                (
                    1,
                    "song-001",
                    _build_payload(_expected_payload_text(b"NOPE" + b"\x00" * 60)),
                )
            ]
        )
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[SplitAcbChunk(path_id=1)],
        )
        with _temp_workdir() as work_dir:
            with self.assertRaises(ReassemblyError) as ctx:
                reassemble_acb(candidate, work_dir)
            self.assertEqual(ctx.exception.stage, "invalid_magic")

    def test_missing_chunk_raises(self) -> None:
        env = _fake_environment(
            [
                (
                    1,
                    "song-001",
                    _build_payload(_expected_payload_text(b"\x40\x55\x54\x46" + b"x" * 60)),
                )
            ]
        )
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[
                SplitAcbChunk(path_id=1),
                SplitAcbChunk(path_id=2),  # not present in the environment
            ],
        )
        with _temp_workdir() as work_dir:
            with self.assertRaises(ReassemblyError) as ctx:
                reassemble_acb(candidate, work_dir)
            self.assertEqual(ctx.exception.stage, "missing_chunk")

    def test_empty_chunk_raises(self) -> None:
        env = _fake_environment([(1, "song-001", "")])
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[SplitAcbChunk(path_id=1)],
        )
        with _temp_workdir() as work_dir:
            with self.assertRaises(ReassemblyError) as ctx:
                reassemble_acb(candidate, work_dir)
            self.assertEqual(ctx.exception.stage, "empty_chunk")

    def test_missing_afs2_marker_raises(self) -> None:
        # Build a chunk that becomes "@UTF" after XOR but lacks AFS2.
        payload = (b"@UTF" + b"\x00" * 124)
        encoded = bytes(b ^ XOR_KEY for b in payload)
        env = _fake_environment(
            [(1, "song-001", _build_payload(_expected_payload_text(encoded)))]
        )
        self._patch(env)
        candidate = SplitAcbCandidate(
            source=Path("song.bundle"),
            sha256="0" * 64,
            container="x.asset",
            cue_sheet="song",
            chunks=[SplitAcbChunk(path_id=1)],
        )
        with _temp_workdir() as work_dir:
            with self.assertRaises(ReassemblyError) as ctx:
                reassemble_acb(candidate, work_dir)
            self.assertEqual(ctx.exception.stage, "missing_afs2")


def _expected_payload_text(payload: bytes) -> str:
    """Convert bytes to the surrogate-escape ``str`` UnityPy returns."""

    return payload.decode("utf-8", errors="surrogateescape")


from contextlib import contextmanager  # noqa: E402
import tempfile  # noqa: E402


@contextmanager
def _temp_workdir():
    with tempfile.TemporaryDirectory() as temporary:
        yield Path(temporary)


if __name__ == "__main__":
    unittest.main()