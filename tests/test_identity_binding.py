"""T4 tests for ``backend.identity.BindingModule`` and internal HTTP routes.

The identity database lives under ``<data_root>/identity/identity.sqlite3``.
These tests build it inside a temporary directory and exercise the public
BindingModule surface plus the FastAPI adapter under ``/internal/v1/``.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

from backend import app as backend_app  # noqa: E402
from backend.config import (  # noqa: E402
    EnabledEnvironment,
    QueryServiceConfig,
)
from backend.contracts import (  # noqa: E402
    Binding,
    BindingInput,
    Channel,
    Principal,
    Region,
    VerificationStatus,
)
from backend.identity import (  # noqa: E402
    AdapterCredential,
    BindingModule,
    IdentityRepository,
)


_QQ_NAMESPACE = "qq-official:fixture-app"
_ONEBOT_NAMESPACE = "onebot:fixture-self"
_GLOBAL_PRODUCTION = "global-production"
_GLOBAL_STAGING = "global-staging"


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _principal(namespace: str = _QQ_NAMESPACE, user: str = "fixture-user") -> Principal:
    return Principal(
        adapter_id="adapter-fixture",
        identity_namespace=namespace,
        platform_user_id=user,
    )


def _input(
    *,
    namespace: str = _QQ_NAMESPACE,
    user: str = "fixture-user",
    env: str = _GLOBAL_PRODUCTION,
    account: str = "fixture-account",
) -> BindingInput:
    return BindingInput(
        identity_namespace=namespace,
        platform_user_id=user,
        game_environment_id=env,
        game_account_id=account,
    )


def _open_module(root: Path) -> BindingModule:
    repository = IdentityRepository(root / "identity" / "identity.sqlite3")
    repository.initialize()
    return BindingModule(repository)


def _config(root: Path) -> QueryServiceConfig:
    return QueryServiceConfig(
        data_root=root / "data",
        host="127.0.0.1",
        port=8090,
        enabled_environments=(
            EnabledEnvironment(region=Region.GLOBAL, channel=Channel.PRODUCTION),
        ),
        freshness_seconds=300,
        cache_control_max_age=30,
    )


class MigrationTest(unittest.TestCase):
    def test_creates_bindings_table_with_unique_constraint(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            repository = IdentityRepository(root / "identity.sqlite3")
            repository.initialize()

            with sqlite3.connect(str(root / "identity.sqlite3")) as conn:
                row = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='bindings'"
                ).fetchone()
                self.assertEqual(row, ("bindings",))

                indexes = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index'"
                ).fetchall()
                index_names = {item[0] for item in indexes}
                self.assertIn("sqlite_autoindex_bindings_1", index_names)


class BindingModuleTest(unittest.TestCase):
    def test_upsert_creates_a_claimed_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            principal = _principal()
            input_ = _input(account="acc-001")

            binding = module.upsert_binding(principal, input_)

            self.assertIsInstance(binding, Binding)
            self.assertEqual(binding.verification_status, VerificationStatus.CLAIMED)
            self.assertEqual(binding.game_account_id, "acc-001")

    def test_upsert_is_idempotent_on_unique_key(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            principal = _principal()

            first = module.upsert_binding(principal, _input(account="acc-001"))
            second = module.upsert_binding(principal, _input(account="acc-002"))

            self.assertEqual(first.id, second.id)
            self.assertEqual(second.game_account_id, "acc-002")

    def test_list_returns_only_current_principal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            module.upsert_binding(
                _principal(user="alice"), _input(account="a-1", user="alice")
            )
            module.upsert_binding(
                _principal(user="bob"), _input(account="b-1", user="bob")
            )

            listed = module.list_bindings(_principal(user="alice"), _GLOBAL_PRODUCTION)

            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].platform_user_id, "alice")

    def test_list_filters_by_environment(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            module.upsert_binding(
                _principal(user="alice"),
                _input(account="a-1", env=_GLOBAL_PRODUCTION, user="alice"),
            )
            module.upsert_binding(
                _principal(user="alice"),
                _input(account="a-2", env=_GLOBAL_STAGING, user="alice"),
            )

            listed = module.list_bindings(_principal(user="alice"), _GLOBAL_PRODUCTION)

            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].game_environment_id, _GLOBAL_PRODUCTION)

    def test_remove_binding_is_idempotent_for_owner(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            binding = module.upsert_binding(_principal(), _input())

            module.remove_binding(_principal(), binding.id)
            # Second remove MUST NOT raise — the operation is idempotent
            # for the current owner.
            module.remove_binding(_principal(), binding.id)

    def test_remove_binding_for_foreign_id_raises_not_visible(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            binding = module.upsert_binding(
                _principal(user="alice"), _input(user="alice")
            )

            with self.assertRaises(BindingModule.NotVisible):
                module.remove_binding(_principal(user="bob"), binding.id)

    def test_list_filters_out_foreign_principals(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)
            module.upsert_binding(
                _principal(user="alice"), _input(account="a-1", user="alice")
            )

            listed = module.list_bindings(_principal(user="bob"), _GLOBAL_PRODUCTION)

            self.assertEqual(listed, ())

    def test_upsert_rejects_writing_verified_status(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            module = _open_module(root)

            with self.assertRaises(BindingModule.ForbiddenVerificationStatus):
                module.upsert_binding_with_status(
                    _principal(),
                    _input(),
                    requested_status=VerificationStatus.VERIFIED,
                )

    def test_bindings_survive_repository_restart(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            first = _open_module(root)
            binding = first.upsert_binding(
                _principal(user="alice"), _input(user="alice")
            )
            first.close()

            second = _open_module(root)

            listed = second.list_bindings(_principal(user="alice"), _GLOBAL_PRODUCTION)
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0].id, binding.id)
            self.assertEqual(listed[0].game_account_id, "fixture-account")
            second.close()


class AdapterAuthTest(unittest.TestCase):
    def test_create_app_starts_when_internal_app_is_missing(self) -> None:
        # The public API MUST keep working when no adapters / binding module
        # is provided. /internal/v1/* simply returns 404.
        with tempfile.TemporaryDirectory() as temporary:
            config = _config(Path(temporary))
            client = TestClient(backend_app.create_app(config))

            response = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
            )

            self.assertEqual(response.status_code, 404)

    def test_missing_authorization_header_returns_401(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config(root)
            module = _open_module(root)
            adapters = (
                AdapterCredential(
                    adapter_id="qq-official-prod",
                    bearer_token="secret-token",
                    allowed_namespaces=(_QQ_NAMESPACE,),
                ),
            )
            app = backend_app.create_app(
                config,
                binding_module=module,
                adapters=adapters,
            )
            client = TestClient(app)

            response = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
                headers={"X-Identity-Namespace": _QQ_NAMESPACE, "X-Platform-User-Id": "u"},
            )

            self.assertEqual(response.status_code, 401)

    def test_invalid_bearer_returns_401(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config(root)
            module = _open_module(root)
            adapters = (
                AdapterCredential(
                    adapter_id="qq-official-prod",
                    bearer_token="correct-token",
                    allowed_namespaces=(_QQ_NAMESPACE,),
                ),
            )
            app = backend_app.create_app(
                config,
                binding_module=module,
                adapters=adapters,
            )
            client = TestClient(app)

            response = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
                headers={
                    "Authorization": "Bearer wrong-token",
                    "X-Identity-Namespace": _QQ_NAMESPACE,
                    "X-Platform-User-Id": "u",
                },
            )

            self.assertEqual(response.status_code, 401)

    def test_unauthorized_namespace_returns_403(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config(root)
            module = _open_module(root)
            adapters = (
                AdapterCredential(
                    adapter_id="qq-official-prod",
                    bearer_token="qq-token",
                    allowed_namespaces=(_QQ_NAMESPACE,),
                ),
                AdapterCredential(
                    adapter_id="onebot-prod",
                    bearer_token="onebot-token",
                    allowed_namespaces=(_ONEBOT_NAMESPACE,),
                ),
            )
            app = backend_app.create_app(
                config,
                binding_module=module,
                adapters=adapters,
            )
            client = TestClient(app)

            response = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
                headers={
                    "Authorization": "Bearer qq-token",
                    "X-Identity-Namespace": _ONEBOT_NAMESPACE,
                    "X-Platform-User-Id": "u",
                },
            )

            self.assertEqual(response.status_code, 403)


class InternalRouteFlowTest(unittest.TestCase):
    def test_full_upsert_list_remove_flow(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config(root)
            module = _open_module(root)
            adapters = (
                AdapterCredential(
                    adapter_id="qq-official-prod",
                    bearer_token="qq-token",
                    allowed_namespaces=(_QQ_NAMESPACE,),
                ),
            )
            app = backend_app.create_app(
                config,
                binding_module=module,
                adapters=adapters,
            )
            client = TestClient(app)
            headers = {
                "Authorization": "Bearer qq-token",
                "X-Identity-Namespace": _QQ_NAMESPACE,
                "X-Platform-User-Id": "alice",
            }

            put = client.put(
                f"/internal/v1/bindings/{_GLOBAL_PRODUCTION}",
                json={"gameAccountId": "acc-001"},
                headers=headers,
            )
            self.assertEqual(put.status_code, 200, msg=put.text)
            binding_id = put.json()["id"]

            listed = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
                headers=headers,
            )
            self.assertEqual(listed.status_code, 200)
            self.assertEqual(len(listed.json()["items"]), 1)
            self.assertEqual(listed.json()["items"][0]["id"], binding_id)

            deleted = client.delete(
                f"/internal/v1/bindings/{binding_id}",
                headers=headers,
            )
            self.assertEqual(deleted.status_code, 204)

            after = client.get(
                "/internal/v1/bindings",
                params={"environmentId": _GLOBAL_PRODUCTION},
                headers=headers,
            )
            self.assertEqual(after.json()["items"], [])

    def test_remove_foreign_binding_returns_404(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = _config(root)
            module = _open_module(root)
            adapters = (
                AdapterCredential(
                    adapter_id="qq-official-prod",
                    bearer_token="qq-token",
                    allowed_namespaces=(_QQ_NAMESPACE,),
                ),
            )
            app = backend_app.create_app(
                config,
                binding_module=module,
                adapters=adapters,
            )
            client = TestClient(app)
            owner_headers = {
                "Authorization": "Bearer qq-token",
                "X-Identity-Namespace": _QQ_NAMESPACE,
                "X-Platform-User-Id": "alice",
            }
            foreign_headers = {
                "Authorization": "Bearer qq-token",
                "X-Identity-Namespace": _QQ_NAMESPACE,
                "X-Platform-User-Id": "bob",
            }

            put = client.put(
                f"/internal/v1/bindings/{_GLOBAL_PRODUCTION}",
                json={"gameAccountId": "acc-001"},
                headers=owner_headers,
            )
            binding_id = put.json()["id"]

            deleted = client.delete(
                f"/internal/v1/bindings/{binding_id}",
                headers=foreign_headers,
            )
            self.assertEqual(deleted.status_code, 404)


if __name__ == "__main__":
    unittest.main()