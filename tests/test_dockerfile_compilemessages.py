"""
Static analysis test for compiling translations at image build (sb-b7h).

locale/*/LC_MESSAGES/*.mo is gitignored, so the image only carries a compiled
German catalog if the Dockerfile runs compilemessages after the source COPY.
It must run at build time, before USER app, so the .mo lands in the image layer
shared across init/app/qcluster/bot (sb-cm5: init's writes never reach app).
"""

import re
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def clear_cache_between_tests():
    """Override the global autouse fixture — these tests need no DB/cache."""
    yield


DOCKERFILE = Path(__file__).parent.parent / "Dockerfile"


def _instructions():
    """Return Dockerfile instructions with backslash continuations joined."""
    joined = re.sub(r"\\\n", " ", DOCKERFILE.read_text())
    return [ln.strip() for ln in joined.splitlines() if ln.strip() and not ln.strip().startswith("#")]


def _index(instructions, predicate, what):
    matches = [i for i, ln in enumerate(instructions) if predicate(ln)]
    assert matches, f"No {what} instruction found in Dockerfile"
    return matches[0]


def test_compilemessages_runs_after_source_copy_and_before_user_app():
    instructions = _instructions()
    compile_at = _index(
        instructions,
        lambda ln: ln.startswith("RUN") and re.search(r"manage\.py\s+compilemessages", ln),
        "RUN ... manage.py compilemessages",
    )
    copy_at = _index(instructions, lambda ln: re.fullmatch(r"COPY\s+\.\s+/app", ln), "COPY . /app")
    user_at = _index(instructions, lambda ln: re.fullmatch(r"USER\s+app", ln), "USER app")
    assert copy_at < compile_at < user_at, (
        f"compilemessages (instruction {compile_at}) must sit after COPY . /app ({copy_at}) and before USER app ({user_at})"
    )
