from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from tools.performance_contract import load_performance_contract


REPO_ROOT = Path(__file__).resolve().parents[1]


class PerformanceContractTest(unittest.TestCase):
    def test_product_v1_keeps_core_and_event_cases(self) -> None:
        contract = load_performance_contract(REPO_ROOT / "config/performance/gates.product-v1.json")
        self.assertEqual(len(contract.browser_cases), 36)
        self.assertIn("/global/zh-CN/events/", contract.load_paths)
        self.assertFalse(any("stories/" in case.path for case in contract.browser_cases))

    def test_product_v1_rejects_substituted_route(self) -> None:
        payload = json.loads((REPO_ROOT / "config/performance/gates.product-v1.json").read_text())
        payload["browser"]["routes"][-1]["id"] = "stories"
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contract.json"
            path.write_text(json.dumps(payload))
            with self.assertRaisesRegex(ValueError, "noncanonical"):
                load_performance_contract(path)

    def test_browser_measurement_waits_for_a_stable_resource_set_before_sampling(self) -> None:
        source = (REPO_ROOT / "tools/performance_browser.cjs").read_text(
            encoding="utf-8"
        )

        settle_call = source.index("await waitForResourceSettle(page);")
        resource_sample = source.index(
            'performance.getEntriesByType("resource").map'
        )
        self.assertLess(settle_call, resource_sample)
        self.assertIn("async function waitForResourceSettle(page)", source)
        self.assertIn(
            'const entries = performance.getEntriesByType("resource")', source
        )
        self.assertIn("count: entries.length", source)
        self.assertIn("resource_measurement_settle_timeout", source)

    def test_v1_contract_expands_stable_browser_cases_and_load_curve(self) -> None:
        contract = load_performance_contract(
            REPO_ROOT / "config/performance/gates.product-v1.json"
        )

        self.assertEqual(contract.schema_version, 1)
        self.assertEqual(len(contract.browser_cases), 36)
        self.assertEqual(
            {case.locale for case in contract.browser_cases},
            {"zh-CN", "en"},
        )
        self.assertEqual(
            {case.viewport.name for case in contract.browser_cases},
            {"desktop", "mobile"},
        )
        self.assertEqual(
            len({case.id for case in contract.browser_cases}),
            len(contract.browser_cases),
        )
        self.assertEqual(
            [
                (stage.concurrency, stage.requests, stage.hard_gate)
                for stage in contract.load_stages
            ],
            [
                (5, 100, True),
                (10, 200, True),
                (20, 200, False),
                (50, 100, False),
            ],
        )

    def test_rejects_an_unsupported_schema_version(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["schemaVersion"] = 2
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "schemaVersion"):
                load_performance_contract(path)

    def test_rejects_an_unsafe_browser_route_template(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["browser"]["routes"][0]["path"] = (
            "https://example.invalid/global/{locale}/"
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "browser route"):
                load_performance_contract(path)

    def test_rejects_an_unsafe_load_path(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["load"]["paths"][0] = "//example.invalid/"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "load path"):
                load_performance_contract(path)

    def test_rejects_duplicate_browser_route_ids(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["browser"]["routes"][1]["id"] = payload["browser"][
            "routes"
        ][0]["id"]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "route id"):
                load_performance_contract(path)

    def test_rejects_a_noncanonical_v1_load_curve(self) -> None:
        payload = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        payload["load"]["stages"][1]["concurrency"] = 11
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "gates.json"
            path.write_text(json.dumps(payload), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "load curve"):
                load_performance_contract(path)

    def test_rejects_a_noncanonical_locale_viewport_or_route_matrix(self) -> None:
        source = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = {
            "locale": lambda value: value["locales"].__setitem__(1, "ja"),
            "viewport": lambda value: value["viewports"][1].__setitem__(
                "width", 391
            ),
            "route matrix": lambda value: value["browser"]["routes"].pop(),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                payload = json.loads(json.dumps(source))
                mutate(payload)
                path = Path(temporary) / "gates.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "browser matrix"):
                    load_performance_contract(path)

    def test_rejects_noncanonical_load_paths_or_warmup(self) -> None:
        source = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = {
            "paths": lambda value: value["load"]["paths"].pop(),
            "warmup": lambda value: value["load"].__setitem__(
                "warmupRequests", 7
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                payload = json.loads(json.dumps(source))
                mutate(payload)
                path = Path(temporary) / "gates.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "load contract"):
                    load_performance_contract(path)

    def test_rejects_non_positive_browser_budgets(self) -> None:
        source = json.loads(
            (REPO_ROOT / "config/performance/gates.product-v1.json").read_text(
                encoding="utf-8"
            )
        )
        mutations = {
            "bytes": lambda value: value["browser"]["routes"][0].__setitem__(
                "maxBytes", 0
            ),
            "requests": lambda value: value["browser"]["routes"][0].__setitem__(
                "maxRequests", 0
            ),
            "byte growth": lambda value: value["browser"].__setitem__(
                "maxByteGrowthRatio", 0
            ),
            "request growth": lambda value: value["browser"].__setitem__(
                "maxRequestGrowth", 0
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                payload = json.loads(json.dumps(source))
                mutate(payload)
                path = Path(temporary) / "gates.json"
                path.write_text(json.dumps(payload), encoding="utf-8")

                with self.assertRaisesRegex(ValueError, "browser budget"):
                    load_performance_contract(path)


if __name__ == "__main__":
    unittest.main()
