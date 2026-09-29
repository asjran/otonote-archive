"""T5 tests for the Query Service delivery surface.

The Query Service is shipped as a separate Docker image
(``Dockerfile.query``) plus systemd units and an env template that the
existing ``tools/deploy_site.sh`` flow does not touch. These tests pin
the contracts from design §11 / §13:

- minimal Python 3.11 slim Bookworm base;
- non-root runtime user, single uvicorn worker;
- only ``backend/`` is shipped in the image (no Node, ffmpeg, site
  media, raw Master, APK or secrets);
- bind mounts enforce ``releases`` is read-only inside the container;
- systemd unit sets ``Restart=on-failure``, ``NoNewPrivileges``, and
  defensive ``MemoryMax``;
- daily backup timer invokes ``backend.identity_backup`` and a manual
  ``query-backup.service`` exists for migration-time snapshots;
- ``deploy/query.env.example`` documents the env vars and includes a
  pinned image digest placeholder.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


class QueryDockerfileTest(unittest.TestCase):
    def test_uses_python_slim_bookworm_base(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile.query").read_text(encoding="utf-8")

        self.assertIn(
            "ARG PYTHON_BASE_IMAGE=python:3.11-slim-bookworm",
            dockerfile,
        )
        self.assertIn("FROM ${PYTHON_BASE_IMAGE}", dockerfile)
        # The image MUST NOT pull Node, ffmpeg, or any media tooling.
        self.assertNotIn("node", dockerfile.lower())
        self.assertNotIn("ffmpeg", dockerfile.lower())
        self.assertNotIn("npm", dockerfile.lower())

    def test_copies_only_backend_and_runtime_files(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile.query").read_text(encoding="utf-8")

        # Required context files.
        self.assertIn("requirements-query.txt", dockerfile)
        self.assertIn("backend ./backend", dockerfile)
        self.assertIn("backend/migrations", dockerfile)

        # Forbidden context files: site, tools, analysis, config, catalog,
        # tests, phone_dump, output, data, dist-matrix, .env files.
        for forbidden in (
            "site ",
            "tools ",
            "analysis ",
            "config ",
            "catalog ",
            "tests ",
            "phone_dump",
            "output ",
            "data ",
            "dist-matrix",
            ".env",
        ):
            # The substring must NOT appear as a ``COPY <token>`` fragment.
            self.assertNotIn(f"COPY {forbidden}", dockerfile)

    def test_runs_as_non_root_with_single_uvicorn_worker(self) -> None:
        dockerfile = (REPO_ROOT / "Dockerfile.query").read_text(encoding="utf-8")

        # Non-root user must be created AND activated (``USER``).
        self.assertRegex(dockerfile, r"adduser|--system|--no-create-home")
        self.assertIn("--uid 10001", dockerfile)
        self.assertIn("--gid 10001", dockerfile)
        self.assertRegex(dockerfile, re.compile(r"^USER\s+\S+", re.MULTILINE))

        # Default command: uvicorn with exactly one worker.
        self.assertRegex(
            dockerfile,
            r'CMD\s+\[?\s*"uvicorn",\s*"backend\.app:create_app_from_environment",\s*"--factory",\s*"--host",\s*"?0\.0\.0\.0"?,\s*"--port",\s*"?8090"?,\s*"--workers",\s*"?1"?',
        )


class QueryRuntimeDependencyTest(unittest.TestCase):
    def test_query_runtime_does_not_import_worker_package(self) -> None:
        source = (REPO_ROOT / "backend/query.py").read_text(encoding="utf-8")

        self.assertNotIn("tools.resource_pipeline", source)


class DockerignoreQueryTest(unittest.TestCase):
    def test_dockerignore_excludes_query_unrelated_paths(self) -> None:
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

        # Patterns that the existing worker image needs MUST stay. The
        # Query image reuses the same ``.dockerignore`` so private inputs
        # remain excluded even when only ``backend/`` is copied.
        for required in (
            "**/*.apk",
            "**/*.zip",
            "**/phone_dump/",
            "**/data/",
            "**/*.secret",
            "**/*.credentials",
            "**/site/",
        ):
            self.assertIn(required, dockerignore)

    def test_dockerignore_includes_query_build_inputs(self) -> None:
        dockerignore = (REPO_ROOT / ".dockerignore").read_text(encoding="utf-8")

        for required in (
            "!Dockerfile.query",
            "!requirements-query.txt",
            "!backend/",
            "!backend/**",
        ):
            self.assertIn(required, dockerignore)


class QuerySystemdTest(unittest.TestCase):
    def test_service_uses_loopback_published_port_and_resource_limits(self) -> None:
        service = (REPO_ROOT / "deploy/query.service").read_text(encoding="utf-8")

        self.assertIn("Type=simple", service)
        self.assertIn("Restart=on-failure", service)
        # ``docker run`` exits 143 after systemd forwards SIGTERM to a
        # gracefully-shutting-down container. Normal stops must not leave the
        # unit in a failed state or trigger Restart=on-failure.
        self.assertIn("SuccessExitStatus=143", service)
        self.assertIn("NoNewPrivileges=true", service)
        # The service delegates environment loading to the env file so
        # all ``OURNOTES_QUERY_*`` variables flow through ``/etc/ournotes/query.env``.
        self.assertIn("EnvironmentFile=/etc/ournotes/query.env", service)
        self.assertIn("--env-file /etc/ournotes/query.env", service)
        self.assertIn("127.0.0.1:8090:8090", service)
        # MemoryMax is a defensive guard but the plan forbids relying on
        # systemd alone — the docker --memory flag MUST also appear.
        self.assertIn("MemoryMax=512M", service)
        self.assertIn("--memory=256m", service)
        self.assertIn("--cpus=0.50", service)
        self.assertIn("--pids-limit=128", service)
        # Read-only release mount + writable identity mount.
        self.assertIn(
            "source=/srv/ournotes-data/releases,target=/data/releases,readonly",
            service,
        )
        self.assertIn(
            "source=/srv/ournotes-data/identity,target=/data/identity",
            service,
        )
        # Image is referenced as a digest in env, never a mutable tag.
        self.assertIn("${OURNOTES_QUERY_IMAGE}", service)

    def test_backup_service_invokes_backend_identity_backup(self) -> None:
        service = (REPO_ROOT / "deploy/query-backup.service").read_text(
            encoding="utf-8"
        )

        self.assertIn("Type=oneshot", service)
        self.assertIn(
            "python3 -m backend.identity_backup", service
        )
        self.assertIn("source=/srv/ournotes-data/identity", service)
        self.assertNotIn(
            "source=/srv/ournotes-data/identity,target=/data/identity,readonly",
            service,
        )

    def test_backup_timer_runs_daily(self) -> None:
        timer = (REPO_ROOT / "deploy/query-backup.timer").read_text(encoding="utf-8")

        self.assertIn("OnCalendar=daily", timer)
        self.assertIn("Persistent=true", timer)
        self.assertIn("Unit=query-backup.service", timer)


class QueryEnvExampleTest(unittest.TestCase):
    def test_env_example_documents_required_variables(self) -> None:
        env = (REPO_ROOT / "deploy/query.env.example").read_text(encoding="utf-8")

        # All public-query knobs from design §10/§11.
        for required in (
            "OURNOTES_DATA_ROOT=",
            "OURNOTES_QUERY_HOST=",
            "OURNOTES_QUERY_PORT=",
            "OURNOTES_QUERY_ENABLED_ENVIRONMENTS=",
            "OURNOTES_QUERY_FRESHNESS_SECONDS=",
            "OURNOTES_QUERY_CACHE_CONTROL_MAX_AGE=",
            "OURNOTES_QUERY_IMAGE=",
        ):
            self.assertIn(required, env)

        self.assertIn("OURNOTES_DATA_ROOT=/data", env)
        self.assertNotIn("OURNOTES_DATA_ROOT=/srv/ournotes-data", env)


class QueryDeploymentRunbookTest(unittest.TestCase):
    def test_uses_installed_unit_name_and_container_uid(self) -> None:
        runbook = (REPO_ROOT / "docs/DEPLOYMENT.md").read_text(encoding="utf-8")

        self.assertNotIn("ournotes-query.service", runbook)
        self.assertIn("systemctl start query.service", runbook)
        self.assertIn("-o 10001 -g 10001", runbook)


if __name__ == "__main__":
    unittest.main()
