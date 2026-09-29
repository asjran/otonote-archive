"""Validated configuration for resource acquisition and publishing."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

try:  # Python 3.11+
    import tomllib
except ModuleNotFoundError:  # Python 3.9-3.10
    import tomli as tomllib

from .models import Channel, Region


class ResourceConfigError(ValueError):
    """Raised when resource platform configuration is incomplete or unsafe."""


@dataclass(frozen=True)
class PlatformConfig:
    data_root: Path
    max_download_concurrency: int
    connect_timeout_seconds: int
    read_timeout_seconds: int
    retry_limit: int
    auto_publish: bool
    max_critical_table_drop_ratio: float


@dataclass(frozen=True)
class EnvironmentConfig:
    environment_id: str
    region: Region
    channel: Channel
    enabled: bool
    client_build_ref: str
    client_generation: str
    adapter: str
    allowed_hosts: tuple[str, ...]
    auth_profile_ref: str
    poll_interval_seconds: int
    activation_state: str
    gate_reason: str | None


def _table(value: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    table = value.get(name)
    if not isinstance(table, dict):
        raise ResourceConfigError(f"missing [{name}] configuration")
    return table


def _required_string(value: Mapping[str, Any], name: str) -> str:
    result = value.get(name)
    if not isinstance(result, str) or not result.strip():
        raise ResourceConfigError(f"{name} must be a non-empty string")
    return result


def _required_integer(
    value: Mapping[str, Any],
    key: str,
    qualified_name: str,
) -> int:
    result = value.get(key)
    if type(result) is not int:
        raise ResourceConfigError(f"{qualified_name} must be an integer")
    return result


def _required_number(
    value: Mapping[str, Any],
    key: str,
    qualified_name: str,
) -> float:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, (int, float)):
        raise ResourceConfigError(f"{qualified_name} must be a number")
    return float(result)


def _required_boolean(
    value: Mapping[str, Any],
    key: str,
    qualified_name: str,
) -> bool:
    result = value.get(key)
    if not isinstance(result, bool):
        raise ResourceConfigError(f"{qualified_name} must be boolean")
    return result


def _reject_inline_secrets(value: Mapping[str, Any], prefix: str = "") -> None:
    sensitive_fragments = (
        "password",
        "passwd",
        "token",
        "cookie",
        "authorization",
        "privatekey",
        "clientsecret",
        "apikey",
    )
    for key, child in value.items():
        path = f"{prefix}.{key}" if prefix else key
        normalized = "".join(character for character in key.lower() if character.isalnum())
        if any(fragment in normalized for fragment in sensitive_fragments):
            raise ResourceConfigError(f"inline secret field is forbidden: {path}")
        if isinstance(child, dict):
            _reject_inline_secrets(child, path)


def load_platform_config(
    path: Path,
    *,
    project_root: Path,
) -> PlatformConfig:
    with path.open("rb") as stream:
        value = tomllib.load(stream)
    _reject_inline_secrets(value)

    storage = _table(value, "storage")
    download = _table(value, "download")
    publishing = _table(value, "publishing")
    validation = _table(value, "validation")

    raw_data_root = storage.get("dataRoot")
    if not isinstance(raw_data_root, str) or not raw_data_root.strip():
        raise ResourceConfigError("storage.dataRoot must be a non-empty string")
    data_root = Path(raw_data_root)
    if not data_root.is_absolute():
        data_root = project_root / data_root

    config = PlatformConfig(
        data_root=data_root,
        max_download_concurrency=_required_integer(
            download,
            "maxConcurrency",
            "download.maxConcurrency",
        ),
        connect_timeout_seconds=_required_integer(
            download,
            "connectTimeoutSeconds",
            "download.connectTimeoutSeconds",
        ),
        read_timeout_seconds=_required_integer(
            download,
            "readTimeoutSeconds",
            "download.readTimeoutSeconds",
        ),
        retry_limit=_required_integer(
            download,
            "retryLimit",
            "download.retryLimit",
        ),
        auto_publish=_required_boolean(
            publishing,
            "autoPublish",
            "publishing.autoPublish",
        ),
        max_critical_table_drop_ratio=_required_number(
            validation,
            "maxCriticalTableDropRatio",
            "validation.maxCriticalTableDropRatio",
        ),
    )

    if config.max_download_concurrency <= 0:
        raise ResourceConfigError("download.maxConcurrency must be positive")
    if config.connect_timeout_seconds <= 0 or config.read_timeout_seconds <= 0:
        raise ResourceConfigError("download timeouts must be positive")
    if config.retry_limit < 0:
        raise ResourceConfigError("download.retryLimit cannot be negative")
    if not 0 <= config.max_critical_table_drop_ratio <= 1:
        raise ResourceConfigError(
            "validation.maxCriticalTableDropRatio must be between 0 and 1"
        )
    return config


def load_environment_config(path: Path) -> EnvironmentConfig:
    with path.open("rb") as stream:
        value = tomllib.load(stream)
    _reject_inline_secrets(value)

    enabled = value.get("enabled")
    if not isinstance(enabled, bool):
        raise ResourceConfigError("enabled must be boolean")
    raw_hosts = value.get("allowedHosts")
    if not isinstance(raw_hosts, list) or not raw_hosts or not all(
        isinstance(host, str) and host.strip() for host in raw_hosts
    ):
        raise ResourceConfigError("allowedHosts must be a non-empty string array")
    raw_poll_interval = value.get("pollIntervalSeconds")
    if (
        not isinstance(raw_poll_interval, int)
        or isinstance(raw_poll_interval, bool)
        or raw_poll_interval <= 0
    ):
        raise ResourceConfigError("pollIntervalSeconds must be a positive integer")
    activation_state = value.get(
        "activationState",
        "active" if enabled else "external_gate",
    )
    if activation_state not in {"active", "external_gate"}:
        raise ResourceConfigError(
            "activationState must be active or external_gate"
        )
    if enabled and activation_state != "active":
        raise ResourceConfigError(
            "enabled environment must have activationState=active"
        )
    gate_reason = value.get("gateReason")
    if activation_state == "external_gate":
        if gate_reason is None:
            gate_reason = "protocol_unverified"
        if not isinstance(gate_reason, str) or not gate_reason.strip():
            raise ResourceConfigError(
                "external_gate environment requires gateReason"
            )
        if not gate_reason.replace("_", "").isalnum():
            raise ResourceConfigError("gateReason must be a safe identifier")
    elif gate_reason is not None:
        raise ResourceConfigError("active environment cannot include gateReason")

    try:
        region = Region(_required_string(value, "region"))
        channel = Channel(_required_string(value, "channel"))
    except ValueError as exc:
        raise ResourceConfigError(f"invalid environment identity: {exc}") from exc

    client_build_ref = _required_string(value, "clientBuildRef")
    expected_prefix = f"{region.value}-{channel.value}-"
    if not client_build_ref.startswith(expected_prefix):
        raise ResourceConfigError(
            "clientBuildRef must belong to "
            f"{region.value}/{channel.value}"
        )

    return EnvironmentConfig(
        environment_id=_required_string(value, "environmentId"),
        region=region,
        channel=channel,
        enabled=enabled,
        client_build_ref=client_build_ref,
        client_generation=_required_string(value, "clientGeneration"),
        adapter=_required_string(value, "adapter"),
        allowed_hosts=tuple(raw_hosts),
        auth_profile_ref=_required_string(value, "authProfileRef"),
        poll_interval_seconds=raw_poll_interval,
        activation_state=activation_state,
        gate_reason=gate_reason,
    )
