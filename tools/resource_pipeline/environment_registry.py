"""Validated discovery of isolated resource synchronization environments."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import EnvironmentConfig, ResourceConfigError, load_environment_config


@dataclass(frozen=True)
class EnvironmentRegistry:
    environments: tuple[EnvironmentConfig, ...]

    @classmethod
    def load(cls, config_root: Path) -> "EnvironmentRegistry":
        environments: list[EnvironmentConfig] = []
        by_id: dict[str, Path] = {}
        auth_identities: dict[str, tuple[str, str]] = {}
        for path in sorted(config_root.glob("*.toml")):
            environment = load_environment_config(path)
            if path.stem != environment.environment_id:
                raise ResourceConfigError(
                    f"environmentId must match configuration filename: {path.name}"
                )
            previous = by_id.get(environment.environment_id)
            if previous is not None:
                raise ResourceConfigError(
                    "duplicate environmentId: " + environment.environment_id
                )
            by_id[environment.environment_id] = path
            if environment.enabled and any(
                host.endswith(".invalid") for host in environment.allowed_hosts
            ):
                raise ResourceConfigError(
                    "enabled environment cannot use a placeholder Host"
                )
            server_identity = (
                environment.region.value,
                environment.channel.value,
            )
            previous_identity = auth_identities.get(environment.auth_profile_ref)
            if (
                previous_identity is not None
                and previous_identity != server_identity
            ):
                raise ResourceConfigError(
                    "authProfileRef cannot be shared across server identities"
                )
            auth_identities[environment.auth_profile_ref] = server_identity
            environments.append(environment)
        return cls(tuple(environments))

    def get(self, environment_id: str) -> EnvironmentConfig:
        for environment in self.environments:
            if environment.environment_id == environment_id:
                return environment
        raise KeyError(environment_id)
