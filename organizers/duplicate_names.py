"""Find "maybe the same" names among Profiles or Venues (sb-x5xh.2 ruling (d)).

Normalization and the Jaro-Winkler bands follow mapular-platform
.claude/skills/geo-analysis references/fuzzy-thresholds.md: >= 0.95 is the
high band, 0.85-0.95 the manual-review band. Nothing here merges; staff merge
in the admin, and those merges become the tuning set for a later threshold.
"""

import re
from dataclasses import dataclass
from itertools import combinations

REVIEW_FLOOR = 0.85
HIGH_FLOOR = 0.95


def normalize(name):
    name = re.sub(r"['.]", "", name.strip().lower())
    name = re.sub(r"[-/&]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def jaro_winkler(a, b):
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    window = max(max(len(a), len(b)) // 2 - 1, 0)
    a_hit = [False] * len(a)
    b_hit = [False] * len(b)
    matches = 0
    for i, ch in enumerate(a):
        for j in range(max(0, i - window), min(len(b), i + window + 1)):
            if not b_hit[j] and b[j] == ch:
                a_hit[i] = b_hit[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    a_seq = [ch for ch, hit in zip(a, a_hit, strict=True) if hit]
    b_seq = [ch for ch, hit in zip(b, b_hit, strict=True) if hit]
    transpositions = sum(x != y for x, y in zip(a_seq, b_seq, strict=True)) / 2
    jaro = (matches / len(a) + matches / len(b) + (matches - transpositions) / matches) / 3
    if jaro <= 0.7:  # Winkler's boost threshold: weak matches get no prefix lift
        return jaro
    prefix = 0
    for x, y in zip(a[:4], b[:4], strict=False):
        if x != y:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


@dataclass(frozen=True)
class Pair:
    band: str  # "exact" (same after normalization), "high", or "review"
    score: float
    a: tuple  # (pk, name)
    b: tuple


def candidate_pairs(rows):
    """rows: iterable of (pk, name). Returns pairs scoring >= REVIEW_FLOOR, best first."""
    normed = [(pk, name, normalize(name)) for pk, name in rows]
    pairs = []
    # debt: all-pairs O(n^2) in Python; fine for hundreds of names. Upgrade
    # (blocking on a name prefix, or SQL similarity) when the report gets slow.
    for (pk_a, name_a, norm_a), (pk_b, name_b, norm_b) in combinations(normed, 2):
        if not norm_a or not norm_b:
            continue
        score = jaro_winkler(norm_a, norm_b)
        if score < REVIEW_FLOOR:
            continue
        if norm_a == norm_b:
            band = "exact"
        elif score >= HIGH_FLOOR:
            band = "high"
        else:
            band = "review"
        pairs.append(Pair(band, score, (pk_a, name_a), (pk_b, name_b)))
    return sorted(pairs, key=lambda p: (-p.score, p.a[1], p.b[1]))
