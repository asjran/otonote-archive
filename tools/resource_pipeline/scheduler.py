"""Independent, lock-protected scheduling across configured environments."""

from __future__ import annotations

import fcntl
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import EnvironmentConfig, load_environment_config


@dataclass(frozen=True)
class EnvironmentRunResult:
    environment_id: str
    status: str
    detail: str | None = None


@dataclass(frozen=True)
class SchedulerReport:
    results: tuple[EnvironmentRunResult, ...]

    @property
    def failed(self) -> bool:
        return any(item.status == "failed" for item in self.results)


EnvironmentRunner = Callable[[EnvironmentConfig], str]


class EnvironmentScheduler:
    """Run every enabled environment independently under a per-env lock."""

    def __init__(self, *, config_root: Path, data_root: Path):
        self._config_root = config_root
        self._lock_root = data_root / "locks"

    def run(self, runner: EnvironmentRunner) -> SchedulerReport:
        results: list[EnvironmentRunResult] = []
        for path in sorted(self._config_root.glob("*.toml")):
            try:
                environment = load_environment_config(path)
            except Exception as exc:
                results.append(
                    EnvironmentRunResult(
                        environment_id=path.stem,
                        status="failed",
                        detail=f"invalid_config:{type(exc).__name__}",
                    )
                )
                continue
            if not environment.enabled:
                continue
            self._lock_root.mkdir(parents=True, exist_ok=True)
            lock_path = self._lock_root / f"{environment.environment_id}.lock"
            with lock_path.open("a+", encoding="utf-8") as lock:
                try:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    results.append(
                        EnvironmentRunResult(
                            environment_id=environment.environment_id,
                            status="locked",
                        )
                    )
                    continue
                try:
                    status = runner(environment)
                    if not isinstance(status, str) or not status.strip():
                        raise ValueError("environment runner returned no status")
                    results.append(
                        EnvironmentRunResult(
                            environment_id=environment.environment_id,
                            status=status,
                        )
                    )
                except Exception as exc:
                    results.append(
                        EnvironmentRunResult(
                            environment_id=environment.environment_id,
                            status="failed",
                            detail=f"runner_failed:{type(exc).__name__}",
                        )
                    )
                finally:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
        return SchedulerReport(tuple(results))

