"""T6 tests for ``tools/query_capacity_check``.

The capacity check is a pure read-only sampler that summarises
CPU, memory, swap, load, disk, and (optionally) docker + systemd state.
It MUST never mutate the host. The tests below drive the sampler with
deterministic synthetic inputs (the sampler accepts an injectable
``reader`` callable) and verify the verdict thresholds from design §14.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from typing import Iterable
from unittest.mock import Mock, patch


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools import query_capacity_check  # noqa: E402


def _reader(
    *,
    cpu_percent: float,
    mem_available_mib: float,
    swap_in_per_sec: float,
    swap_out_per_sec: float,
    load5: float,
    disk_free_mib: float,
    oom_count: int = 0,
    swap_in_samples: Iterable[float] = (),
    swap_out_samples: Iterable[float] = (),
) -> "query_capacity_check.SystemSample":
    sample = query_capacity_check.SystemSample(
        cpu_percent=cpu_percent,
        mem_available_mib=mem_available_mib,
        swap_in_per_sec=swap_in_per_sec,
        swap_out_per_sec=swap_out_per_sec,
        load5=load5,
        disk_free_mib=disk_free_mib,
        oom_count=oom_count,
    )
    sample.swap_in_samples = list(swap_in_samples)
    sample.swap_out_samples = list(swap_out_samples)
    return sample


class VerdictTest(unittest.TestCase):
    def test_pass_when_all_thresholds_are_met(self) -> None:
        verdict = query_capacity_check.evaluate(
            _reader(
                cpu_percent=40.0,
                mem_available_mib=600.0,
                swap_in_per_sec=0.0,
                swap_out_per_sec=0.0,
                load5=0.6,
                disk_free_mib=4096.0,
                swap_in_samples=[0.0, 0.0, 0.0],
                swap_out_samples=[0.0, 0.0, 0.0],
            )
        )

        self.assertEqual(verdict.status, "pass")
        self.assertEqual(verdict.failures, ())

    def test_fail_when_memory_below_budget(self) -> None:
        verdict = query_capacity_check.evaluate(
            _reader(
                cpu_percent=40.0,
                mem_available_mib=350.0,  # < 400 MiB budget
                swap_in_per_sec=0.0,
                swap_out_per_sec=0.0,
                load5=0.6,
                disk_free_mib=4096.0,
                swap_in_samples=[0.0],
                swap_out_samples=[0.0],
            )
        )

        self.assertEqual(verdict.status, "fail")
        self.assertTrue(
            any(
                ("memavailable" in failure.lower())
                or ("mib" in failure.lower())
                for failure in verdict.failures
            )
        )

    def test_fail_when_three_consecutive_swap_samples_are_nonzero(self) -> None:
        verdict = query_capacity_check.evaluate(
            _reader(
                cpu_percent=40.0,
                mem_available_mib=600.0,
                swap_in_per_sec=0.0,
                swap_out_per_sec=0.0,
                load5=0.6,
                disk_free_mib=4096.0,
                # Design §14: no 3 consecutive 5-second samples may show
                # swap-in/out. Two non-zero samples is allowed; three is
                # not.
                swap_in_samples=[0.5, 0.5, 0.5, 0.0, 0.7],
                swap_out_samples=[0.5, 0.5, 0.5, 0.0, 0.6],
            )
        )

        self.assertEqual(verdict.status, "fail")
        self.assertTrue(
            any("swap" in failure.lower() for failure in verdict.failures)
        )

    def test_fail_when_load_average_exceeds_budget(self) -> None:
        verdict = query_capacity_check.evaluate(
            _reader(
                cpu_percent=40.0,
                mem_available_mib=600.0,
                swap_in_per_sec=0.0,
                swap_out_per_sec=0.0,
                load5=2.4,  # > 1.5 budget
                disk_free_mib=4096.0,
                swap_in_samples=[0.0],
                swap_out_samples=[0.0],
            )
        )

        self.assertEqual(verdict.status, "fail")
        self.assertTrue(
            any("load" in failure.lower() for failure in verdict.failures)
        )

    def test_fail_when_oom_event_present(self) -> None:
        verdict = query_capacity_check.evaluate(
            _reader(
                cpu_percent=40.0,
                mem_available_mib=600.0,
                swap_in_per_sec=0.0,
                swap_out_per_sec=0.0,
                load5=0.6,
                disk_free_mib=4096.0,
                oom_count=1,
                swap_in_samples=[0.0],
                swap_out_samples=[0.0],
            )
        )

        self.assertEqual(verdict.status, "fail")
        self.assertTrue(
            any("oom" in failure.lower() for failure in verdict.failures)
        )


class SamplingTest(unittest.TestCase):
    def test_default_sampler_returns_a_complete_sample(self) -> None:
        sample = query_capacity_check.collect_sample()
        for field in (
            "cpu_percent",
            "mem_available_mib",
            "swap_in_per_sec",
            "swap_out_per_sec",
            "load5",
            "disk_free_mib",
            "oom_count",
        ):
            self.assertTrue(hasattr(sample, field), msg=f"missing {field}")
        self.assertGreaterEqual(sample.mem_available_mib, 0.0)
        self.assertGreaterEqual(sample.disk_free_mib, 0.0)

    def test_window_sampler_uses_swap_deltas_and_oom_delta(self) -> None:
        samples = iter(
            [
                _reader(
                    cpu_percent=20.0 + index,
                    mem_available_mib=600.0 - index,
                    swap_in_per_sec=0.0,
                    swap_out_per_sec=0.0,
                    load5=0.5,
                    disk_free_mib=4096.0,
                )
                for index in range(3)
            ]
        )
        vmstats = iter(
            [
                {"pswpin": 100, "pswpout": 50},
                {"pswpin": 105, "pswpout": 50},
                {"pswpin": 105, "pswpout": 55},
                {"pswpin": 110, "pswpout": 60},
            ]
        )
        oom_counts = iter([7, 8])
        sleeper = Mock()

        sample = query_capacity_check.collect_window(
            sample_count=3,
            interval_seconds=5.0,
            sleeper=sleeper,
            sample_reader=lambda: next(samples),
            vmstat_reader=lambda: next(vmstats),
            oom_reader=lambda: next(oom_counts),
        )

        self.assertEqual(sample.swap_in_samples, [1.0, 0.0, 1.0])
        self.assertEqual(sample.swap_out_samples, [0.0, 1.0, 1.0])
        self.assertEqual(sample.swap_in_per_sec, 1.0)
        self.assertEqual(sample.swap_out_per_sec, 1.0)
        self.assertEqual(sample.oom_count, 1)
        self.assertEqual(sleeper.call_count, 3)

    @patch("tools.query_capacity_check.subprocess.run")
    def test_oom_sampler_executes_dmesg_instead_of_reading_binary(
        self, run: Mock
    ) -> None:
        run.return_value = Mock(
            returncode=0,
            stdout="normal\nOut of memory: Killed process 123\noom-kill event\n",
        )

        with patch(
            "tools.query_capacity_check.shutil.which", return_value="/bin/dmesg"
        ):
            count = query_capacity_check._oom_count_from_dmesg()

        self.assertEqual(count, 2)
        run.assert_called_once()


class CliTest(unittest.TestCase):
    def test_main_returns_nonzero_when_verdict_fails(self) -> None:
        sample = _reader(
            cpu_percent=40.0,
            mem_available_mib=100.0,  # way below budget
            swap_in_per_sec=0.0,
            swap_out_per_sec=0.0,
            load5=0.6,
            disk_free_mib=4096.0,
            swap_in_samples=[0.0],
            swap_out_samples=[0.0],
        )
        exit_code = query_capacity_check.main(
            sampler=lambda: sample, argv=[]
        )
        self.assertEqual(exit_code, 1)

    def test_main_returns_zero_when_verdict_passes(self) -> None:
        sample = _reader(
            cpu_percent=40.0,
            mem_available_mib=600.0,
            swap_in_per_sec=0.0,
            swap_out_per_sec=0.0,
            load5=0.6,
            disk_free_mib=4096.0,
            swap_in_samples=[0.0],
            swap_out_samples=[0.0],
        )
        exit_code = query_capacity_check.main(
            sampler=lambda: sample, argv=[]
        )
        self.assertEqual(exit_code, 0)


if __name__ == "__main__":
    unittest.main()
