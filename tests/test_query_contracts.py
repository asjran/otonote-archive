"""T1 contract tests for the Dynamic Query Service surface.

These tests pin the calling surface for downstream modules:
``backend.query`` (T2), ``backend.app`` (T3), ``backend.identity`` (T4).
They must not import FastAPI, sqlite3, or ``tools.resource_pipeline.release_repository``.

Tests read the four canonical fixtures under ``tests/fixtures/query`` and
exercise every supported value combination from the design.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from backend import contracts  # noqa: E402
from backend.contracts import (  # noqa: E402
    Availability,
    Binding,
    BindingInput,
    Channel,
    Dataset,
    DatasetResult,
    Freshness,
    Locale,
    Page,
    Principal,
    Provenance,
    QueryIdentity,
    QuerySpec,
    Region,
    ReleaseRef,
    VerificationStatus,
    Warning,
)


FIXTURES = REPO_ROOT / "tests" / "fixtures" / "query"


class ContractModuleImportsTest(unittest.TestCase):
    """T1 explicitly forbids pulling heavy dependencies into contracts."""

    def test_contracts_module_does_not_import_heavy_dependencies(self) -> None:
        # Inspect the source file directly so the assertion does not depend
        # on the order in which other tests run (later tests may legitimately
        # import ``tools.resource_pipeline.release_repository``).
        import ast

        contracts_path = Path(contracts.__file__).resolve()
        tree = ast.parse(contracts_path.read_text(encoding="utf-8"))
        imported_roots: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_roots.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module is None or node.level > 0:
                    continue
                imported_roots.add(node.module.split(".")[0])

        forbidden = {"fastapi", "uvicorn", "httpx", "sqlite3", "starlette"}
        leaked = forbidden.intersection(imported_roots)
        self.assertFalse(
            leaked,
            msg=f"contracts.py imports forbidden modules: {sorted(leaked)}",
        )
        self.assertFalse(
            any("release_repository" in root for root in imported_roots),
            msg="contracts.py imports tools.resource_pipeline.release_repository",
        )


class EnumContractTest(unittest.TestCase):
    def test_region_values(self) -> None:
        self.assertEqual({region.value for region in Region}, {"global"})

    def test_channel_values(self) -> None:
        self.assertEqual(
            {channel.value for channel in Channel}, {"staging", "production"}
        )

    def test_locale_values(self) -> None:
        self.assertEqual(
            {locale.value for locale in Locale}, {"zh-CN", "zh-TW", "ja", "en"}
        )

    def test_dataset_values(self) -> None:
        self.assertEqual(
            {dataset.value for dataset in Dataset},
            {"events", "rankings", "gacha-pools", "shops"},
        )

    def test_state_dimensions_are_independent_enums(self) -> None:
        self.assertEqual(
            {status.value for status in Availability}, {"available", "unavailable"}
        )
        self.assertEqual(
            {status.value for status in Freshness}, {"fresh", "stale", "unknown"}
        )
        self.assertEqual(
            {status.value for status in Provenance},
            {"configured", "observed", "historical", "predicted", "unknown"},
        )

    def test_verification_status_values(self) -> None:
        self.assertEqual(
            {status.value for status in VerificationStatus},
            {"claimed", "verified", "revoked"},
        )


class QuerySpecValidationTest(unittest.TestCase):
    def test_defaults_match_documented_contract(self) -> None:
        spec = QuerySpec(
            region=Region.GLOBAL,
            channel=Channel.PRODUCTION,
            locale=Locale.JA,
        )
        self.assertEqual(spec.region, Region.GLOBAL)
        self.assertEqual(spec.channel, Channel.PRODUCTION)
        self.assertEqual(spec.locale, Locale.JA)
        self.assertIsNone(spec.season_id)
        self.assertIsNone(spec.cursor)
        self.assertEqual(spec.limit, 20)

    def test_rejects_unknown_region_string(self) -> None:
        with self.assertRaises(ValueError):
            QuerySpec(
                region="cn",  # type: ignore[arg-type]
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
            )

    def test_rejects_limit_below_one(self) -> None:
        with self.assertRaises(ValueError):
            QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                limit=0,
            )

    def test_rejects_limit_above_one_hundred(self) -> None:
        with self.assertRaises(ValueError):
            QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                limit=101,
            )

    def test_rejects_empty_cursor(self) -> None:
        with self.assertRaises(ValueError):
            QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                cursor="   ",
            )

    def test_rejects_empty_season_id(self) -> None:
        with self.assertRaises(ValueError):
            QuerySpec(
                region=Region.GLOBAL,
                channel=Channel.PRODUCTION,
                locale=Locale.JA,
                season_id="",
            )

    def test_season_id_only_valid_for_rankings(self) -> None:
        # season_id is the only optional query field; Dataset ranking is the
        # only one that interprets it. Constructing the spec without that
        # coupling still must succeed.
        spec = QuerySpec(
            region=Region.GLOBAL,
            channel=Channel.PRODUCTION,
            locale=Locale.JA,
            season_id="season-1",
        )
        self.assertEqual(spec.season_id, "season-1")


class TimeStampValidationTest(unittest.TestCase):
    def test_accepts_utc_z_suffix(self) -> None:
        contracts.require_utc_timestamp("2026-08-04T00:00:00Z")

    def test_accepts_explicit_offset(self) -> None:
        contracts.require_utc_timestamp("2026-08-04T08:00:00+00:00")
        contracts.require_utc_timestamp("2026-08-04T16:00:00+08:00")

    def test_rejects_naive_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            contracts.require_utc_timestamp("2026-08-04T00:00:00")

    def test_rejects_malformed_timestamp(self) -> None:
        with self.assertRaises(ValueError):
            contracts.require_utc_timestamp("not-a-timestamp")


class DatasetResultConstructionTest(unittest.TestCase):
    def test_build_minimum_available_fresh_configured(self) -> None:
        result = DatasetResult(
            dataset_schema_version=1,
            dataset=Dataset.EVENTS,
            query=QueryIdentity(
                region=Region.GLOBAL.value,
                channel=Channel.PRODUCTION.value,
                locale=Locale.JA.value,
            ),
            release=ReleaseRef(content_release_id="global-production-content-1"),
            availability=Availability.AVAILABLE,
            freshness=Freshness.FRESH,
            provenance=Provenance.CONFIGURED,
            observed_at="2026-08-04T00:00:00Z",
            generated_at="2026-08-04T00:00:10Z",
            expires_at="2026-08-04T00:20:00Z",
            warnings=(),
            page=Page(limit=20, next_cursor=None),
            items=(),
        )
        self.assertEqual(result.schema_version, 1)
        self.assertEqual(result.dataset, Dataset.EVENTS)

    def test_three_dimensions_compose_independently(self) -> None:
        result = DatasetResult(
            dataset_schema_version=1,
            dataset=Dataset.RANKINGS,
            query=QueryIdentity(
                region=Region.GLOBAL.value,
                channel=Channel.PRODUCTION.value,
                locale=Locale.JA.value,
            ),
            release=ReleaseRef(
                content_release_id="global-production-content-1",
                observation_release_id="global-production-obs-1",
            ),
            availability=Availability.AVAILABLE,
            freshness=Freshness.STALE,
            provenance=Provenance.OBSERVED,
            observed_at="2026-08-03T12:00:00Z",
            generated_at="2026-08-04T00:00:10Z",
            expires_at=None,
            warnings=(
                Warning(
                    code="upstream_unavailable",
                    message="observation older than 12 hours",
                ),
            ),
            page=Page(limit=20, next_cursor=None),
            items=(),
        )
        self.assertEqual(result.availability, Availability.AVAILABLE)
        self.assertEqual(result.freshness, Freshness.STALE)
        self.assertEqual(result.provenance, Provenance.OBSERVED)

    def test_rejects_naive_observed_at(self) -> None:
        with self.assertRaises(ValueError):
            DatasetResult(
                dataset_schema_version=1,
                dataset=Dataset.EVENTS,
                query=QueryIdentity(
                    region=Region.GLOBAL.value,
                    channel=Channel.PRODUCTION.value,
                    locale=Locale.JA.value,
                ),
                release=ReleaseRef(content_release_id="global-production-content-1"),
                availability=Availability.AVAILABLE,
                freshness=Freshness.FRESH,
                provenance=Provenance.CONFIGURED,
                observed_at="2026-08-04T00:00:00",
                generated_at="2026-08-04T00:00:10Z",
                expires_at=None,
                warnings=(),
                page=Page(limit=20, next_cursor=None),
                items=(),
            )


class DatasetResultSerializationTest(unittest.TestCase):
    def test_to_dict_uses_camel_case_keys(self) -> None:
        result = DatasetResult(
            dataset_schema_version=1,
            dataset=Dataset.EVENTS,
            query=QueryIdentity(
                region=Region.GLOBAL.value,
                channel=Channel.PRODUCTION.value,
                locale=Locale.JA.value,
            ),
            release=ReleaseRef(
                content_release_id="global-production-content-1",
                observation_release_id="global-production-obs-1",
            ),
            availability=Availability.AVAILABLE,
            freshness=Freshness.STALE,
            provenance=Provenance.OBSERVED,
            observed_at="2026-08-03T12:00:00Z",
            generated_at="2026-08-04T00:00:10Z",
            expires_at="2026-08-04T00:20:00Z",
            warnings=(Warning(code="upstream_unavailable", message="stale"),),
            page=Page(limit=20, next_cursor="cursor-2"),
            items=({"eventId": "event-1"},),
        )

        payload = result.to_dict()

        self.assertEqual(payload["schemaVersion"], 1)
        self.assertEqual(payload["datasetSchemaVersion"], 1)
        self.assertEqual(payload["dataset"], "events")
        self.assertEqual(
            payload["query"],
            {"region": "global", "channel": "production", "locale": "ja"},
        )
        self.assertEqual(
            payload["release"],
            {
                "contentReleaseId": "global-production-content-1",
                "observationReleaseId": "global-production-obs-1",
            },
        )
        self.assertEqual(payload["availability"], "available")
        self.assertEqual(payload["freshness"], "stale")
        self.assertEqual(payload["provenance"], "observed")
        self.assertEqual(payload["observedAt"], "2026-08-03T12:00:00Z")
        self.assertEqual(payload["generatedAt"], "2026-08-04T00:00:10Z")
        self.assertEqual(payload["expiresAt"], "2026-08-04T00:20:00Z")
        self.assertEqual(
            payload["warnings"],
            [{"code": "upstream_unavailable", "message": "stale"}],
        )
        self.assertEqual(payload["page"], {"limit": 20, "nextCursor": "cursor-2"})

    def test_from_dict_round_trip(self) -> None:
        result = DatasetResult(
            dataset_schema_version=1,
            dataset=Dataset.SHOPS,
            query=QueryIdentity(
                region=Region.GLOBAL.value,
                channel=Channel.STAGING.value,
                locale=Locale.ZH_CN.value,
            ),
            release=ReleaseRef(content_release_id="global-staging-content-1"),
            availability=Availability.AVAILABLE,
            freshness=Freshness.FRESH,
            provenance=Provenance.CONFIGURED,
            observed_at=None,
            generated_at="2026-08-04T00:00:00Z",
            expires_at=None,
            warnings=(),
            page=Page(limit=20, next_cursor=None),
            items=(),
        )
        rebuilt = DatasetResult.from_dict(result.to_dict())
        self.assertEqual(rebuilt, result)


class PrincipalAndBindingContractTest(unittest.TestCase):
    def test_principal_requires_non_empty_components(self) -> None:
        with self.assertRaises(ValueError):
            Principal(
                adapter_id="",
                identity_namespace="qq-official:fixture",
                platform_user_id="fixture-user",
            )
        with self.assertRaises(ValueError):
            Principal(
                adapter_id="adapter-fixture",
                identity_namespace="   ",
                platform_user_id="fixture-user",
            )
        with self.assertRaises(ValueError):
            Principal(
                adapter_id="adapter-fixture",
                identity_namespace="qq-official:fixture",
                platform_user_id="",
            )

    def test_identity_namespace_must_include_prefix(self) -> None:
        # Design §9.1 namespaces look like ``qq-official:<app-id>`` or
        # ``onebot:<self-id>``. Contracts must reject plain strings so that
        # future code can trust the prefix for routing.
        with self.assertRaises(ValueError):
            Principal(
                adapter_id="adapter-fixture",
                identity_namespace="bare-namespace",
                platform_user_id="fixture-user",
            )

    def test_binding_input_uses_environment_id_not_region(self) -> None:
        # game_environment_id must be a full identifier like
        # ``global-production``; the bare region ``jp`` is explicitly rejected
        # to avoid coupling binding writes to Region alone.
        with self.assertRaises(ValueError):
            BindingInput(
                identity_namespace="qq-official:fixture",
                platform_user_id="fixture-user",
                game_environment_id="global",
                game_account_id="fixture-account",
            )

    def test_binding_carries_all_required_fields(self) -> None:
        binding = Binding(
            id="binding-1",
            identity_namespace="qq-official:fixture",
            platform_user_id="fixture-user",
            game_environment_id="global-production",
            game_account_id="fixture-account",
            verification_status=VerificationStatus.CLAIMED,
            created_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        self.assertEqual(binding.verification_status, VerificationStatus.CLAIMED)
        self.assertEqual(binding.game_environment_id, "global-production")
        self.assertNotEqual(binding.game_environment_id, "global")

    def test_binding_input_rejects_empty_account_id(self) -> None:
        with self.assertRaises(ValueError):
            BindingInput(
                identity_namespace="qq-official:fixture",
                platform_user_id="fixture-user",
                game_environment_id="global-production",
                game_account_id="",
            )

    def test_binding_to_dict_redacts_sensitive_values(self) -> None:
        # Logging and JSON snapshots must not leak full identifiers. The
        # serialization keeps the IDs but constrains visibility through a
        # separate ``summary`` field that callers are expected to log.
        binding = Binding(
            id="binding-1",
            identity_namespace="qq-official:fixture",
            platform_user_id="fixture-user-abcdef",
            game_environment_id="global-production",
            game_account_id="fixture-account-1234567890",
            verification_status=VerificationStatus.CLAIMED,
            created_at="2026-08-04T00:00:00Z",
            updated_at="2026-08-04T00:00:00Z",
        )
        summary = binding.summary()
        self.assertNotIn("abcdef", summary)
        self.assertNotIn("1234567890", summary)


class FixtureRoundTripTest(unittest.TestCase):
    """Round-trip every fixture through ``DatasetResult.from_dict``/``to_dict``."""

    def _load(self, name: str) -> dict[str, Any]:
        return json.loads((FIXTURES / name).read_text(encoding="utf-8"))

    def _round_trip(self, name: str) -> DatasetResult:
        payload = self._load(name)
        result = DatasetResult.from_dict(payload)
        self.assertEqual(result.to_dict(), payload)
        return result

    def test_events_fixture_round_trip(self) -> None:
        result = self._round_trip("events.json")
        self.assertEqual(result.dataset, Dataset.EVENTS)
        self.assertEqual(result.provenance, Provenance.CONFIGURED)
        self.assertEqual(result.availability, Availability.AVAILABLE)
        self.assertEqual(result.freshness, Freshness.FRESH)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["eventId"], "event-fixture-1")

    def test_rankings_fixture_returns_unavailable(self) -> None:
        # The ranking fixture MUST NOT pretend to expose observed data:
        # design §15 requires a clear ``no_observation`` signal until the
        # ObservationRelease Repository is implemented (a later task).
        result = self._round_trip("rankings.json")
        self.assertEqual(result.dataset, Dataset.RANKINGS)
        self.assertEqual(result.availability, Availability.UNAVAILABLE)
        self.assertEqual(result.freshness, Freshness.UNKNOWN)
        self.assertEqual(result.provenance, Provenance.UNKNOWN)
        self.assertEqual(result.items, ())
        self.assertTrue(result.warnings)
        self.assertEqual(result.warnings[0].code, "no_observation")

    def test_gacha_pools_fixture_round_trip(self) -> None:
        result = self._round_trip("gacha-pools.json")
        self.assertEqual(result.dataset, Dataset.GACHA_POOLS)
        self.assertEqual(result.provenance, Provenance.CONFIGURED)
        self.assertEqual(result.availability, Availability.AVAILABLE)
        self.assertTrue(result.warnings)
        self.assertEqual(result.warnings[0].code, "locale_fallback")
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["poolId"], "pool-fixture-1")

    def test_shops_fixture_round_trip(self) -> None:
        result = self._round_trip("shops.json")
        self.assertEqual(result.dataset, Dataset.SHOPS)
        self.assertEqual(result.provenance, Provenance.CONFIGURED)
        self.assertEqual(result.availability, Availability.AVAILABLE)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0]["shopId"], "shop-fixture-1")


class FixturePrivacyTest(unittest.TestCase):
    """Step 8 forbids real player identity, tokens, hosts, or credentials."""

    def test_no_fixture_contains_secrets_or_hosts(self) -> None:
        forbidden_substrings = (
            "token",
            "password",
            "cookie",
            "authorization",
            "http://",
            "https://",
            "cdn.example",
            "real-account",
        )
        for path in sorted(FIXTURES.glob("*.json")):
            text = path.read_text(encoding="utf-8").lower()
            for needle in forbidden_substrings:
                self.assertNotIn(
                    needle,
                    text,
                    msg=f"{path.name} must not contain {needle!r}",
                )


if __name__ == "__main__":
    unittest.main()