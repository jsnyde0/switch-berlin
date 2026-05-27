"""
Content cleaning seam for platform projections (kb-a4u.4).

Per-platform content-policy rules live in kb-o0j (open bead).
This module provides the seam that engine.py calls; at v0 it is an identity stub.

ADR-008 D2: no speculative abstraction — the seam exists so the call site is wired,
but the real rules land as a separate bead (soft dep, do not implement here).
"""


def clean_for_platform(text: str, platform: str) -> str:
    """
    Apply per-platform content-policy cleaning to text.

    v0: identity stub — returns text unchanged.
    Real per-platform rules land in kb-o0j.
    The seam is wired here so the call site in engine.py is not dead code.

    Args:
        text: The raw text to clean.
        platform: Target platform identifier (e.g. 'fetlife', 'telegram', 'switch').
                  This is connection.platform — a plain platform string, not a
                  compound encoding.

    Returns:
        Cleaned text (at v0: identical to input).
    """
    # ADR-008 D2: no speculative per-platform logic here.
    # kb-o0j owns the real cleaning rules.
    return text
