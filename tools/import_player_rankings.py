"""Publish a validated, server-labelled ranking export atomically."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.player_rankings import SERVERS, validate_observation


def publish(source: Path, root: Path, server: str) -> Path:
    return publish_observation(json.loads(source.read_text()), root, server)


def publish_observation(value: dict, root: Path, server: str) -> Path:
    value = validate_observation(value, server)
    target = root / server / "current.json"
    new_directory = not target.parent.exists()
    target.parent.mkdir(parents=True, exist_ok=True)
    if new_directory:
        # Capture may run with a private umask; the public read-only service
        # needs traversal of the newly created, public observations directory.
        os.chmod(target.parent, 0o755)
    fd, temporary = tempfile.mkstemp(prefix=".ranking-", dir=target.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            json.dump(value, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        # The public read-only service runs under a separate, unprivileged UID.
        os.chmod(temporary, 0o644)
        os.replace(temporary, target)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()
    return target


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("--root", required=True, type=Path, help="Query data root / observations")
    parser.add_argument("--server", required=True, choices=sorted(SERVERS))
    args = parser.parse_args()
    print(publish(args.source, args.root, args.server))
