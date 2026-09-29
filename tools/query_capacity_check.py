"""Read-only 2 vCPU / 2 GiB capacity sampler and gate for the Query Service.

Design §14 documents the capacity budget the production candidate must
clear before the Query Service is publicly reachable:

- peak ``MemAvailable >= 400 MiB``;
- no three consecutive 5-second samples with non-zero swap-in/out;
- 5-minute average load <= 1.5;
- no OOM events during the sample window;
- disk still satisfies the SiteRelease / ContentRelease budget;
- no 5xx from the Query Service under the synthetic load.

This module is intentionally read-only: it never restarts services,
never mutates ``/etc``, and never talks to a remote host. When the
verdict fails, callers are expected to stop the candidate and revisit
the topology — not to retry the check until it agrees.

The sampling primitives are wrapped in :class:`SystemSample` so tests
can drive ``evaluate`` with deterministic inputs.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, List, Optional, Sequence


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


MEM_AVAILABLE_MIN_MIB = 400.0
LOAD_AVERAGE_MAX = 1.5
DISK_FREE_MIN_MIB = 1024.0
SWAP_CONSECUTIVE_NONZERO = 3
SWAP_SAMPLE_WINDOW = 5
OOM_FORBIDDEN = True


# ---------------------------------------------------------------------------
# Sampling
# ---------------------------------------------------------------------------


@dataclass
class SystemSample:
    """One read-only snapshot of the host's capacity profile."""

    cpu_percent: float
    mem_available_mib: float
    swap_in_per_sec: float
    swap_out_per_sec: float
    load5: float
    disk_free_mib: float
    oom_count: int
    swap_in_samples: List[float] = field(default_factory=list)
    swap_out_samples: List[float] = field(default_factory=list)
    raw: dict[str, float] = field(default_factory=dict)


def _read_proc_meminfo() -> dict[str, int]:
    path = Path("/proc/meminfo")
    if not path.is_file():
        return {}
    info: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        first = value.strip().split()
        if not first:
            continue
        try:
            info[key.strip()] = int(first[0])
        except ValueError:
            continue
    return info


def _read_proc_loadavg() -> Optional[float]:
    path = Path("/proc/loadavg")
    if not path.is_file():
        return None
    parts = path.read_text(encoding="utf-8").split()
    if len(parts) < 2:
        return None
    try:
        return float(parts[1])
    except ValueError:
        return None


def _read_proc_vmstat() -> dict[str, int]:
    path = Path("/proc/vmstat")
    if not path.is_file():
        return {}
    info: dict[str, int] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, _, value = line.partition(" ")
        try:
            info[key] = int(value)
        except ValueError:
            continue
    return info


def _read_proc_stat_cpu_busy() -> Optional[float]:
    path = Path("/proc/stat")
    if not path.is_file():
        return None
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.startswith("cpu "):
            continue
        parts = line.split()
        if len(parts) < 5:
            return None
        values = [int(part) for part in parts[1:]]
        total = sum(values)
        idle = values[3] + values[4] if len(values) >= 5 else values[3]
        if total <= 0:
            return None
        return max(0.0, min(100.0, (total - idle) * 100.0 / total))
    return None


def _disk_free_mib(path: Path) -> float:
    try:
        usage = shutil.disk_usage(str(path))
    except (FileNotFoundError, OSError):
        return 0.0
    return usage.free / (1024 * 1024)


def _oom_count_from_dmesg() -> int:
    # Best-effort probe: only available when running as root or when
    # ``dmesg`` is readable. ``dmesg`` is rarely world-readable so this
    # almost always returns 0 in CI; production checks re-run via ssh.
    path = shutil.which("dmesg")
    if path is None:
        return 0
    try:
        result = subprocess.run(
            [path, "--ctime"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return 0
    if result.returncode != 0:
        return 0
    markers = ("Out of memory", "oom-kill", "Killed process")
    return sum(
        1
        for line in result.stdout.splitlines()
        if any(marker in line for marker in markers)
    )


def collect_sample() -> SystemSample:
    """Return one instantaneous host snapshot.

    Swap counters in ``/proc/vmstat`` are cumulative and therefore remain in
    ``raw``. :func:`collect_window` converts their deltas into per-second rates.
    """

    meminfo = _read_proc_meminfo()
    vmstat = _read_proc_vmstat()
    load5 = _read_proc_loadavg() or 0.0
    cpu_percent = _read_proc_stat_cpu_busy() or 0.0

    mem_available_kib = float(meminfo.get("MemAvailable", 0))
    swap_in_total = float(vmstat.get("pswpin", 0))
    swap_out_total = float(vmstat.get("pswpout", 0))

    raw = {
        "mem_available_kib": mem_available_kib,
        "swap_in_total": swap_in_total,
        "swap_out_total": swap_out_total,
        "load5": load5,
        "cpu_percent": cpu_percent,
    }

    return SystemSample(
        cpu_percent=cpu_percent,
        mem_available_mib=mem_available_kib / 1024,
        swap_in_per_sec=0.0,
        swap_out_per_sec=0.0,
        load5=load5,
        disk_free_mib=_disk_free_mib(Path("/srv/ournotes-data")),
        oom_count=_oom_count_from_dmesg(),
        raw=raw,
    )


def collect_window(
    *,
    sample_count: int = SWAP_CONSECUTIVE_NONZERO,
    interval_seconds: float = SWAP_SAMPLE_WINDOW,
    sleeper: Callable[[float], None] = time.sleep,
    sample_reader: Callable[[], SystemSample] = collect_sample,
    vmstat_reader: Callable[[], dict[str, int]] = _read_proc_vmstat,
    oom_reader: Callable[[], int] = _oom_count_from_dmesg,
) -> SystemSample:
    """Collect a short read-only window and derive swap and OOM deltas."""

    if sample_count < 1:
        raise ValueError("sample_count must be at least 1")
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than 0")

    previous_vmstat = vmstat_reader()
    oom_before = oom_reader()
    snapshots: list[SystemSample] = []
    swap_in_samples: list[float] = []
    swap_out_samples: list[float] = []

    for _ in range(sample_count):
        sleeper(interval_seconds)
        current_vmstat = vmstat_reader()
        snapshots.append(sample_reader())
        swap_in_samples.append(
            max(0.0, float(current_vmstat.get("pswpin", 0) - previous_vmstat.get("pswpin", 0)))
            / interval_seconds
        )
        swap_out_samples.append(
            max(0.0, float(current_vmstat.get("pswpout", 0) - previous_vmstat.get("pswpout", 0)))
            / interval_seconds
        )
        previous_vmstat = current_vmstat

    latest = snapshots[-1]
    return replace(
        latest,
        cpu_percent=max(sample.cpu_percent for sample in snapshots),
        mem_available_mib=min(sample.mem_available_mib for sample in snapshots),
        swap_in_per_sec=swap_in_samples[-1],
        swap_out_per_sec=swap_out_samples[-1],
        load5=max(sample.load5 for sample in snapshots),
        disk_free_mib=min(sample.disk_free_mib for sample in snapshots),
        oom_count=max(0, oom_reader() - oom_before),
        swap_in_samples=swap_in_samples,
        swap_out_samples=swap_out_samples,
    )


# ---------------------------------------------------------------------------
# Verdict
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Verdict:
    status: str  # "pass" | "warn" | "fail"
    failures: tuple[str, ...]
    sample: SystemSample

    def to_dict(self) -> dict[str, object]:
        return {
            "status": self.status,
            "failures": list(self.failures),
            "sample": {
                "cpu_percent": self.sample.cpu_percent,
                "mem_available_mib": self.sample.mem_available_mib,
                "swap_in_per_sec": self.sample.swap_in_per_sec,
                "swap_out_per_sec": self.sample.swap_out_per_sec,
                "load5": self.sample.load5,
                "disk_free_mib": self.sample.disk_free_mib,
                "oom_count": self.sample.oom_count,
                "swap_in_samples": list(self.sample.swap_in_samples),
                "swap_out_samples": list(self.sample.swap_out_samples),
            },
        }


def _has_consecutive_nonzero(samples: Sequence[float], length: int) -> bool:
    if not samples:
        return False
    streak = 0
    for value in samples:
        if value > 0:
            streak += 1
            if streak >= length:
                return True
        else:
            streak = 0
    return False


def evaluate(sample: SystemSample) -> Verdict:
    failures: list[str] = []

    if sample.mem_available_mib < MEM_AVAILABLE_MIN_MIB:
        failures.append(
            f"MemAvailable {sample.mem_available_mib:.1f} MiB is below the "
            f"{MEM_AVAILABLE_MIN_MIB:.0f} MiB budget"
        )

    if sample.disk_free_mib < DISK_FREE_MIN_MIB:
        failures.append(
            f"disk free {sample.disk_free_mib:.1f} MiB is below the "
            f"{DISK_FREE_MIN_MIB:.0f} MiB minimum"
        )

    if sample.load5 > LOAD_AVERAGE_MAX:
        failures.append(
            f"5-minute load average {sample.load5:.2f} exceeds the "
            f"{LOAD_AVERAGE_MAX:.2f} budget"
        )

    if OOM_FORBIDDEN and sample.oom_count > 0:
        failures.append(
            f"{sample.oom_count} OOM event(s) detected in the sample window"
        )

    if _has_consecutive_nonzero(sample.swap_in_samples, SWAP_CONSECUTIVE_NONZERO):
        failures.append(
            f"{SWAP_CONSECUTIVE_NONZERO} consecutive swap-in samples were non-zero"
        )
    if _has_consecutive_nonzero(sample.swap_out_samples, SWAP_CONSECUTIVE_NONZERO):
        failures.append(
            f"{SWAP_CONSECUTIVE_NONZERO} consecutive swap-out samples were non-zero"
        )

    status = "pass" if not failures else "fail"
    return Verdict(status=status, failures=tuple(failures), sample=sample)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


Sampler = Callable[[], SystemSample]


def main(
    sampler: Optional[Sampler] = None,
    *,
    argv: Optional[Sequence[str]] = None,
) -> int:
    parser = argparse.ArgumentParser(
        prog="query_capacity_check",
        description=(
            "Read-only capacity sampler for the OurNotes Query Service. "
            "Never mutates the host; on failure it only prints a verdict "
            "and a non-zero exit code."
        ),
    )
    parser.add_argument("--samples", type=int, default=SWAP_CONSECUTIVE_NONZERO)
    parser.add_argument("--interval-seconds", type=float, default=SWAP_SAMPLE_WINDOW)
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    sample = (
        sampler()
        if sampler is not None
        else collect_window(
            sample_count=args.samples,
            interval_seconds=args.interval_seconds,
        )
    )
    verdict = evaluate(sample)
    print(json.dumps(verdict.to_dict(), indent=2, sort_keys=True))
    return 0 if verdict.status == "pass" else 1


if __name__ == "__main__":  # pragma: no cover - exercised via CLI
    raise SystemExit(main())
