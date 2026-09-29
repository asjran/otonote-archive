#!/usr/bin/env python3
"""Create versioned local snapshots of OurNotes data stored on a server."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Optional, Sequence

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - depends on the local Python
    try:
        import tomli as tomllib
    except ModuleNotFoundError as error:  # pragma: no cover
        raise SystemExit(
            "Python 3.11+ or the 'tomli' package is required to read TOML."
        ) from error


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "server-sync.local.toml"
SSH_TARGET_PATTERN = re.compile(
    r"^(?:[A-Za-z0-9._-]+@)?[A-Za-z0-9._:-]+$"
)
SOURCE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
REMOTE_PATH_PATTERN = re.compile(r"^/[A-Za-z0-9._/-]+$")
TIMESTAMP_PATTERN = re.compile(r"^[0-9]{8}T[0-9]{6}Z$")
SSH_OPTIONS = (
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=15",
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=3",
    "-o",
    "StrictHostKeyChecking=accept-new",
)

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class SyncError(RuntimeError):
    """Raised when configuration or snapshot creation is unsafe or incomplete."""


@dataclass(frozen=True)
class SourceConfig:
    name: str
    remote_path: str
    enabled: bool
    required: bool
    excludes: tuple[str, ...]


@dataclass(frozen=True)
class SyncConfig:
    ssh_target: str
    destination: Path
    sources: tuple[SourceConfig, ...]


def _require_table(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise SyncError(f"{label} must be a TOML table")
    return value


def _require_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise SyncError(f"{label} must be a non-empty string")
    return value.strip()


def _optional_bool(value: Any, label: str, default: bool) -> bool:
    if value is None:
        return default
    if not isinstance(value, bool):
        raise SyncError(f"{label} must be true or false")
    return value


def _parse_excludes(value: Any, label: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise SyncError(f"{label} must be an array of strings")

    excludes: list[str] = []
    for index, item in enumerate(value):
        exclude = _require_string(item, f"{label}[{index}]")
        if "\n" in exclude or "\r" in exclude or "\0" in exclude:
            raise SyncError(f"{label}[{index}] contains an unsafe character")
        excludes.append(exclude)
    return tuple(excludes)


def _validate_remote_path(remote_path: str, label: str) -> str:
    if not REMOTE_PATH_PATTERN.fullmatch(remote_path):
        raise SyncError(
            f"{label} must be an absolute path containing only safe path characters"
        )
    normalized = PurePosixPath(remote_path)
    if ".." in normalized.parts or str(normalized) != remote_path.rstrip("/"):
        raise SyncError(f"{label} must be a normalized absolute path")
    if str(normalized) == "/":
        raise SyncError(f"{label} cannot be the server root")
    return str(normalized)


def _validate_destination(destination: Path, repo_root: Path) -> Path:
    resolved = destination.expanduser().resolve()
    repository = repo_root.resolve()
    user_root = Path.home().resolve()

    if resolved == Path(resolved.anchor):
        raise SyncError("backup.destination cannot be a filesystem root")
    if resolved == user_root:
        raise SyncError("backup.destination cannot be the user home directory")
    if resolved == repository or repository in resolved.parents:
        raise SyncError("backup.destination must be outside the Git checkout")
    return resolved


def load_config(
    config_path: Path, repo_root: Path = REPO_ROOT
) -> SyncConfig:
    try:
        with config_path.open("rb") as stream:
            raw = tomllib.load(stream)
    except FileNotFoundError as error:
        raise SyncError(
            f"configuration file does not exist: {config_path}\n"
            "Copy config/server-sync.example.toml to "
            "config/server-sync.local.toml first."
        ) from error
    except tomllib.TOMLDecodeError as error:
        raise SyncError(f"invalid TOML in {config_path}: {error}") from error

    if raw.get("version") != 1:
        raise SyncError("version must be 1")

    server = _require_table(raw.get("server"), "server")
    ssh_target = _require_string(server.get("sshTarget"), "server.sshTarget")
    if not SSH_TARGET_PATTERN.fullmatch(ssh_target):
        raise SyncError("server.sshTarget contains unsafe characters")

    backup = _require_table(raw.get("backup"), "backup")
    destination_value = _require_string(
        backup.get("destination"), "backup.destination"
    )
    destination_path = Path(destination_value)
    if not destination_path.is_absolute():
        destination_path = repo_root / destination_path
    destination = _validate_destination(destination_path, repo_root)

    source_values = raw.get("sources")
    if not isinstance(source_values, list) or not source_values:
        raise SyncError("sources must contain at least one source table")

    sources: list[SourceConfig] = []
    names: set[str] = set()
    for index, raw_source in enumerate(source_values):
        label = f"sources[{index}]"
        source = _require_table(raw_source, label)
        name = _require_string(source.get("name"), f"{label}.name")
        if not SOURCE_NAME_PATTERN.fullmatch(name):
            raise SyncError(
                f"{label}.name must use letters, numbers, dot, underscore or dash"
            )
        if name in names:
            raise SyncError(f"duplicate source name: {name}")
        names.add(name)

        remote_path = _validate_remote_path(
            _require_string(source.get("remotePath"), f"{label}.remotePath"),
            f"{label}.remotePath",
        )
        enabled = _optional_bool(
            source.get("enabled"), f"{label}.enabled", True
        )
        required = _optional_bool(
            source.get("required"), f"{label}.required", True
        )
        excludes = _parse_excludes(
            source.get("excludes"), f"{label}.excludes"
        )
        sources.append(
            SourceConfig(
                name=name,
                remote_path=remote_path,
                enabled=enabled,
                required=required,
                excludes=excludes,
            )
        )

    if not any(source.enabled for source in sources):
        raise SyncError("at least one source must be enabled")

    return SyncConfig(
        ssh_target=ssh_target,
        destination=destination,
        sources=tuple(sources),
    )


def _run_command(
    command: Sequence[str],
    *,
    capture_output: bool = False,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        check=False,
        text=True,
        stdout=subprocess.PIPE if capture_output else None,
        stderr=subprocess.PIPE if capture_output else None,
        cwd=cwd,
    )


def _check_dependencies() -> None:
    missing = [
        command for command in ("ssh", "rsync") if shutil.which(command) is None
    ]
    if missing:
        raise SyncError(
            "required local command is missing: " + ", ".join(missing)
        )


def _ssh_command(ssh_target: str, remote_command: str) -> list[str]:
    return ["ssh", *SSH_OPTIONS, ssh_target, remote_command]


def check_remote_source(
    config: SyncConfig,
    source: SourceConfig,
    runner: CommandRunner = _run_command,
) -> bool:
    remote_command = f"test -d {shlex.quote(source.remote_path)}"
    result = runner(
        _ssh_command(config.ssh_target, remote_command),
        capture_output=True,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    detail = (result.stderr or result.stdout or "").strip()
    suffix = f": {detail}" if detail else ""
    raise SyncError(
        f"SSH check failed for {source.remote_path} "
        f"(exit {result.returncode}){suffix}"
    )


def build_rsync_command(
    config: SyncConfig,
    source: SourceConfig,
    local_directory: Path,
    link_destination: Optional[Path],
) -> list[str]:
    ssh_transport = "ssh " + " ".join(SSH_OPTIONS)
    command = [
        "rsync",
        "-a",
        "--safe-links",
        "--stats",
        "--human-readable",
        "-e",
        ssh_transport,
    ]
    if link_destination is not None:
        command.append(f"--link-dest={link_destination.resolve()}")
    command.extend(f"--exclude={exclude}" for exclude in source.excludes)
    command.extend(
        [
            f"{config.ssh_target}:{source.remote_path.rstrip('/')}/",
            f"{local_directory}/",
        ]
    )
    return command


def _ensure_destination_parent(destination: Path) -> None:
    candidate = destination
    while not candidate.exists() and candidate != candidate.parent:
        candidate = candidate.parent
    if not candidate.is_dir():
        raise SyncError(
            f"backup destination parent is not a directory: {candidate}"
        )
    if not os.access(candidate, os.W_OK):
        raise SyncError(
            f"backup destination parent is not writable: {candidate}"
        )


def _snapshot_from_latest(destination: Path) -> Optional[Path]:
    latest = destination / "latest"
    if not latest.exists() and not latest.is_symlink():
        return None
    if not latest.is_symlink():
        raise SyncError(f"latest must be a symbolic link: {latest}")

    target_text = os.readlink(latest)
    if Path(target_text).is_absolute():
        raise SyncError("latest must use a relative snapshot target")
    if not TIMESTAMP_PATTERN.fullmatch(target_text):
        raise SyncError(f"latest has an invalid snapshot target: {target_text}")

    target = (destination / target_text).resolve()
    try:
        target.relative_to(destination.resolve())
    except ValueError as error:
        raise SyncError("latest points outside the backup destination") from error
    if not target.is_dir():
        raise SyncError(f"latest snapshot directory is missing: {target}")
    if not (target / "backup-manifest.json").is_file():
        raise SyncError(f"latest snapshot manifest is missing: {target}")
    return target


def _tree_stats(root: Path) -> dict[str, int]:
    files = 0
    symlinks = 0
    logical_bytes = 0
    for current_root, directory_names, file_names in os.walk(
        root, followlinks=False
    ):
        current_path = Path(current_root)
        for name in [*directory_names, *file_names]:
            path = current_path / name
            path_stat = path.lstat()
            if stat.S_ISLNK(path_stat.st_mode):
                symlinks += 1
            elif stat.S_ISREG(path_stat.st_mode):
                files += 1
                logical_bytes += path_stat.st_size
    return {
        "files": files,
        "symlinks": symlinks,
        "logicalBytes": logical_bytes,
    }


def _git_commit(
    repo_root: Path = REPO_ROOT,
    runner: CommandRunner = _run_command,
) -> str:
    result = runner(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        cwd=repo_root,
    )
    if result.returncode != 0:
        return "unknown"
    commit = (result.stdout or "").strip()
    return commit if re.fullmatch(r"[0-9a-fA-F]{40}", commit) else "unknown"


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _update_latest(destination: Path, snapshot_name: str) -> None:
    latest = destination / "latest"
    if latest.exists() and not latest.is_symlink():
        raise SyncError(f"refusing to replace non-symlink latest: {latest}")
    temporary = destination / f".latest.{os.getpid()}.tmp"
    if temporary.exists() or temporary.is_symlink():
        raise SyncError(f"temporary latest path already exists: {temporary}")
    temporary.symlink_to(snapshot_name)
    try:
        os.replace(temporary, latest)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise


def _timestamp_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _print_plan(
    config: SyncConfig,
    states: Sequence[tuple[SourceConfig, bool]],
    previous: Optional[Path],
) -> None:
    print(f"SSH target: {config.ssh_target}")
    print(f"Backup destination: {config.destination}")
    print(
        "Previous snapshot: "
        + (previous.name if previous is not None else "(none)")
    )
    for source, present in states:
        status = "ready" if present else "skipped (optional path missing)"
        print(f"  - {source.name}: {source.remote_path} [{status}]")


def sync_server_data(
    config: SyncConfig,
    *,
    dry_run: bool = False,
    runner: CommandRunner = _run_command,
    timestamp: Optional[str] = None,
    check_dependencies: bool = True,
) -> Optional[Path]:
    if check_dependencies:
        _check_dependencies()
    _ensure_destination_parent(config.destination)

    source_states: list[tuple[SourceConfig, bool]] = []
    for source in config.sources:
        if not source.enabled:
            continue
        present = check_remote_source(config, source, runner)
        if not present and source.required:
            raise SyncError(
                f"required remote directory does not exist: {source.remote_path}"
            )
        source_states.append((source, present))

    previous = (
        _snapshot_from_latest(config.destination)
        if config.destination.exists()
        else None
    )
    _print_plan(config, source_states, previous)
    if dry_run:
        print("Dry run complete; no snapshot was created.")
        return None

    config.destination.mkdir(parents=True, exist_ok=True)
    snapshot_name = timestamp or _timestamp_now()
    if not TIMESTAMP_PATTERN.fullmatch(snapshot_name):
        raise SyncError(f"invalid snapshot timestamp: {snapshot_name}")
    snapshot = config.destination / snapshot_name
    partial = config.destination / f".{snapshot_name}.partial"
    if snapshot.exists() or partial.exists():
        raise SyncError(
            f"snapshot or partial directory already exists for {snapshot_name}"
        )
    partial.mkdir()

    manifest_sources: list[dict[str, Any]] = []
    for source, present in source_states:
        source_manifest: dict[str, Any] = {
            "name": source.name,
            "remotePath": source.remote_path,
            "excludes": list(source.excludes),
        }
        if not present:
            source_manifest["status"] = "skipped"
            source_manifest["reason"] = "optional remote directory missing"
            manifest_sources.append(source_manifest)
            continue

        local_directory = partial / source.name
        local_directory.mkdir()
        link_destination = None
        if previous is not None:
            previous_source = previous / source.name
            if previous_source.is_dir():
                link_destination = previous_source

        command = build_rsync_command(
            config,
            source,
            local_directory,
            link_destination,
        )
        print(f"Syncing {source.name} from {source.remote_path}...")
        result = runner(command)
        if result.returncode != 0:
            raise SyncError(
                f"rsync failed for {source.name} "
                f"(exit {result.returncode}); partial snapshot kept at {partial}"
            )

        source_manifest["status"] = "synced"
        source_manifest["localPath"] = source.name
        source_manifest.update(_tree_stats(local_directory))
        manifest_sources.append(source_manifest)

    manifest = {
        "version": 1,
        "createdAt": datetime.strptime(
            snapshot_name, "%Y%m%dT%H%M%SZ"
        )
        .replace(tzinfo=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
        "sshTarget": config.ssh_target,
        "gitCommit": _git_commit(runner=runner),
        "previousSnapshot": previous.name if previous is not None else None,
        "sources": manifest_sources,
    }
    _write_manifest(partial / "backup-manifest.json", manifest)
    os.replace(partial, snapshot)
    _update_latest(config.destination, snapshot_name)
    print(f"Snapshot created: {snapshot}")
    return snapshot


def _parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Create a versioned local snapshot of OurNotes server data."
        )
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG_PATH,
        help=(
            "TOML configuration path "
            "(default: config/server-sync.local.toml)"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate local and remote inputs without creating a snapshot",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parse_args(argv)
    config_path = args.config
    if not config_path.is_absolute():
        config_path = (Path.cwd() / config_path).resolve()
    try:
        config = load_config(config_path)
        sync_server_data(config, dry_run=args.dry_run)
    except SyncError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
