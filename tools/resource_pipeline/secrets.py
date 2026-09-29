"""Secret resolution by opaque profile reference."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Mapping


class SecretUnavailable(RuntimeError):
    def __init__(self, auth_profile_ref: str, reason: str):
        self.auth_profile_ref = auth_profile_ref
        self.reason = reason
        super().__init__(f"auth profile {auth_profile_ref} is {reason}")


@dataclass(frozen=True)
class BasicAuthCredentials:
    auth_profile_ref: str
    username: str = field(repr=False)
    password: str = field(repr=False)


class EnvironmentSecretProvider:
    def __init__(
        self,
        *,
        environ: Mapping[str, str] | None = None,
        now: Callable[[], datetime] | None = None,
    ):
        self._environ = os.environ if environ is None else environ
        self._now = now or (lambda: datetime.now(timezone.utc))

    @staticmethod
    def _prefix(auth_profile_ref: str) -> str:
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", auth_profile_ref):
            raise ValueError("auth_profile_ref must be a path-safe lowercase identifier")
        normalized = re.sub(r"[^A-Za-z0-9]", "_", auth_profile_ref).upper()
        return f"OURNOTES_SECRET_{normalized}"

    def resolve_basic(self, auth_profile_ref: str) -> BasicAuthCredentials:
        prefix = self._prefix(auth_profile_ref)
        username = self._environ.get(f"{prefix}_USER")
        password = self._environ.get(f"{prefix}_PASS")
        if not username or not password:
            raise SecretUnavailable(auth_profile_ref, "missing")
        raw_expiry = self._environ.get(f"{prefix}_EXPIRES_AT")
        if raw_expiry:
            try:
                expiry = datetime.fromisoformat(raw_expiry.replace("Z", "+00:00"))
            except ValueError as exc:
                raise SecretUnavailable(auth_profile_ref, "invalid") from exc
            if expiry.tzinfo is None:
                raise SecretUnavailable(auth_profile_ref, "invalid")
            if self._now() >= expiry:
                raise SecretUnavailable(auth_profile_ref, "expired")
        return BasicAuthCredentials(
            auth_profile_ref=auth_profile_ref,
            username=username,
            password=password,
        )
