"""
Static analysis tests for Dockerfile base image pinning (kb-mhi).

Verifies that all FROM and COPY --from lines reference immutable sha256 digests
so builds are deterministic and supply-chain compromises become reviewable PRs.
"""

import re
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Override the global autouse fixture — these tests need no DB/cache."""
    yield


DOCKERFILE = Path(__file__).parent.parent / "Dockerfile"

# Lines we care about (zero-indexed positions in the file are not stable, so
# we match by content instead)
FROM_PATTERN = re.compile(r"^FROM\s+(\S+)", re.MULTILINE)
COPY_FROM_PATTERN = re.compile(r"^COPY\s+--from=(\S+)", re.MULTILINE)
DIGEST_RE = re.compile(r"@sha256:[a-f0-9]{64}")


def _get_image_refs():
    """Return all image refs used in FROM and COPY --from lines."""
    content = DOCKERFILE.read_text()
    refs = FROM_PATTERN.findall(content) + COPY_FROM_PATTERN.findall(content)
    return refs


class TestDockerfileSha256Pins:
    """All base images must be pinned to immutable sha256 digests."""

    def test_dockerfile_exists(self):
        assert DOCKERFILE.exists(), "Dockerfile not found at repo root"

    def test_all_image_refs_have_digest(self):
        """Every external FROM and COPY --from image must contain @sha256:<digest>.

        Internal stage names (e.g. COPY --from=frontend) are skipped because
        they reference a build-stage alias, not a registry image.
        """
        content = DOCKERFILE.read_text()
        # Collect FROM stage names so we can skip internal COPY --from refs
        stage_aliases = set()
        for line in content.splitlines():
            m = re.match(r"^FROM\s+\S+\s+AS\s+(\S+)", line.strip(), re.IGNORECASE)
            if m:
                stage_aliases.add(m.group(1).lower())

        refs = _get_image_refs()
        assert refs, "No FROM or COPY --from lines found in Dockerfile"
        # Skip internal stage aliases
        external_refs = [r for r in refs if r.lower() not in stage_aliases]
        unpinned = [r for r in external_refs if not DIGEST_RE.search(r)]
        assert unpinned == [], (
            f"These image refs are not pinned to a sha256 digest: {unpinned}"
        )

    def test_node_image_pinned(self):
        """node:22-slim must be pinned."""
        content = DOCKERFILE.read_text()
        node_lines = [
            ln.strip()
            for ln in content.splitlines()
            if ln.strip().startswith("FROM") and "node" in ln
        ]
        assert node_lines, "No node FROM line found"
        for line in node_lines:
            assert DIGEST_RE.search(line), (
                f"node FROM line is not digest-pinned: {line!r}"
            )

    def test_python_image_pinned(self):
        """python:3.13-slim-bookworm must be pinned."""
        content = DOCKERFILE.read_text()
        python_lines = [
            ln.strip()
            for ln in content.splitlines()
            if ln.strip().startswith("FROM") and "python" in ln
        ]
        assert python_lines, "No python FROM line found"
        for line in python_lines:
            assert DIGEST_RE.search(line), (
                f"python FROM line is not digest-pinned: {line!r}"
            )

    def test_uv_image_pinned(self):
        """ghcr.io/astral-sh/uv must be pinned and not use :latest."""
        content = DOCKERFILE.read_text()
        uv_lines = [ln.strip() for ln in content.splitlines() if "astral-sh/uv" in ln]
        assert uv_lines, "No uv COPY --from line found"
        for line in uv_lines:
            # Strip inline comment before checking for :latest in the image ref
            code_part = line.split("#")[0].rstrip()
            assert DIGEST_RE.search(code_part), (
                f"uv COPY --from line is not digest-pinned: {line!r}"
            )
            assert ":latest" not in code_part, (
                f"uv image still uses :latest tag: {line!r}"
            )

    def test_uv_uses_explicit_version_not_latest(self):
        """uv image must use an explicit version tag, not :latest."""
        content = DOCKERFILE.read_text()
        uv_lines = [ln.strip() for ln in content.splitlines() if "astral-sh/uv" in ln]
        assert uv_lines, "No uv COPY --from line found"
        for line in uv_lines:
            # Strip inline comment before checking for :latest in the image ref
            code_part = line.split("#")[0].rstrip()
            assert ":latest" not in code_part, f"uv image still uses :latest: {line!r}"
            # Must have a version tag like :0.X.Y
            assert re.search(r"uv:\d+\.\d+\.\d+", code_part), (
                f"uv image does not have an explicit semver tag: {line!r}"
            )
