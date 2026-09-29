"""Environment-only configuration for the Dynamic Query Service.

The HTTP adapter is intentionally thin: every value comes from an explicit
environment variable. There is no implicit ``./config`` discovery and no
filesystem probing — the same image can run on developer laptops, CI, and
the production server without code changes.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Sequence

from backend.contracts import Channel, Region


class ConfigurationError(ValueError):
    """Raised when the Query Service environment is incomplete or invalid."""


DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8090
DEFAULT_FRESHNESS_SECONDS = 300
DEFAULT_CACHE_CONTROL_MAX_AGE = 30


@dataclass(frozen=True)
class EnabledEnvironment:
    region: Region
    channel: Channel


@dataclass(frozen=True)
class QueryServiceConfig:
    data_root: Path
    host: str
    port: int
    enabled_environments: tuple[EnabledEnvironment, ...]
    freshness_seconds: int
    cache_control_max_age: int

    def __post_init__(self) -> None:
        if not isinstance(self.data_root, Path):
            raise ConfigurationError("data_root must be a Path")
        if not self.host.strip():
            raise ConfigurationError("host cannot be empty")
        if not isinstance(self.port, int) or isinstance(self.port, bool):
            raise ConfigurationError("port must be an integer")
        if not (1 <= self.port <= 65535):
            raise ConfigurationError(f"port must be 1..65535, got {self.port}")
        if not isinstance(self.freshness_seconds, int) or self.freshness_seconds < 0:
            raise ConfigurationError("freshness_seconds must be a non-negative integer")
        if (
            not isinstance(self.cache_control_max_age, int)
            or isinstance(self.cache_control_max_age, bool)
            or self.cache_control_max_age < 0
        ):
            raise ConfigurationError("cache_control_max_age must be a non-negative integer")
        if not self.enabled_environments:
            raise ConfigurationError(
                "at least one enabled environment is required for readiness"
            )
        seen: set[tuple[Region, Channel]] = set()
        for env in self.enabled_environments:
            if (env.region, env.channel) in seen:
                raise ConfigurationError(
                    f"enabled environment {env.region.value}/{env.channel.value} is duplicated"
                )
            seen.add((env.region, env.channel))

    @property
    def release_root(self) -> Path:
        """Path to the ``releases`` directory under ``data_root``."""

        return self.data_root / "releases"

    @property
    def identity_root(self) -> Path:
        """Path to the ``identity`` directory under ``data_root``."""

        return self.data_root / "identity"


def load_from_environment(
    environment: Mapping[str, str] | None = None,
) -> QueryServiceConfig:
    """Build a :class:`QueryServiceConfig` from ``environment`` or ``os.environ``."""

    env = os.environ if environment is None else environment

    data_root_value = env.get("OURNOTES_DATA_ROOT")
    if not data_root_value or not data_root_value.strip():
        raise ConfigurationError("OURNOTES_DATA_ROOT must be set")
    data_root = Path(data_root_value).expanduser().resolve()

    host = (env.get("OURNOTES_QUERY_HOST") or DEFAULT_HOST).strip()

    port_raw = env.get("OURNOTES_QUERY_PORT")
    if port_raw is None or port_raw.strip() == "":
        port = DEFAULT_PORT
    else:
        try:
            port = int(port_raw)
        except ValueError as exc:
            raise ConfigurationError(
                f"OURNOTES_QUERY_PORT must be an integer, got {port_raw!r}"
            ) from exc

    enabled = _parse_enabled_environments(
        env.get("OURNOTES_QUERY_ENABLED_ENVIRONMENTS")
    )

    freshness_seconds = _parse_int(
        env.get("OURNOTES_QUERY_FRESHNESS_SECONDS"),
        DEFAULT_FRESHNESS_SECONDS,
        "OURNOTES_QUERY_FRESHNESS_SECONDS",
    )

    cache_max_age = _parse_int(
        env.get("OURNOTES_QUERY_CACHE_CONTROL_MAX_AGE"),
        DEFAULT_CACHE_CONTROL_MAX_AGE,
        "OURNOTES_QUERY_CACHE_CONTROL_MAX_AGE",
    )

    return QueryServiceConfig(
        data_root=data_root,
        host=host,
        port=port,
        enabled_environments=enabled,
        freshness_seconds=freshness_seconds,
        cache_control_max_age=cache_max_age,
    )


def _parse_enabled_environments(
    raw: str | None,
) -> tuple[EnabledEnvironment, ...]:
    if raw is None or not raw.strip():
        raise ConfigurationError(
            "OURNOTES_QUERY_ENABLED_ENVIRONMENTS must list at least one "
            "'<region>-<channel>' pair"
        )
    environments: list[EnabledEnvironment] = []
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        if "-" not in token:
            raise ConfigurationError(
                f"enabled environment {token!r} must look like '<region>-<channel>'"
            )
        region_token, channel_token = token.split("-", 1)
        try:
            region = Region(region_token)
        except ValueError as exc:
            raise ConfigurationError(
                f"unknown region {region_token!r} in enabled environment"
            ) from exc
        try:
            channel = Channel(channel_token)
        except ValueError as exc:
            raise ConfigurationError(
                f"unknown channel {channel_token!r} in enabled environment"
            ) from exc
        environments.append(EnabledEnvironment(region=region, channel=channel))
    if not environments:
        raise ConfigurationError(
            "OURNOTES_QUERY_ENABLED_ENVIRONMENTS must list at least one "
            "'<region>-<channel>' pair"
        )
    return tuple(environments)


def _parse_int(raw: str | None, default: int, field_name: str) -> int:
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigurationError(f"{field_name} must be an integer, got {raw!r}") from exc
    if value < 0:
        raise ConfigurationError(f"{field_name} cannot be negative")
    return value


__all__ = [
    "ConfigurationError",
    "EnabledEnvironment",
    "QueryServiceConfig",
    "load_from_environment",
    "DEFAULT_CACHE_CONTROL_MAX_AGE",
    "DEFAULT_FRESHNESS_SECONDS",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
]