"""Username permutation generator.

Real people reuse a handle with small, predictable tweaks. We model the most
common ones so the scanner can look for the same person under a close alias.
The generator is capped (``limit``) so a run can never explode into thousands
of requests.
"""
from __future__ import annotations

import re
from typing import List

_SEPARATORS = ("", ".", "_", "-")
_SUFFIXES = ("dev", "official", "hq", "01", "123", "99")


def _tokens(seed: str) -> List[str]:
    """Split 'john.doe99' into ['john', 'doe', '99'] (letters and digits separate)."""
    return re.findall(r"[a-z]+|\d+", seed.strip().lower())


def generate(seed: str, limit: int = 12) -> List[str]:
    """Return the seed first, then ranked variants, de-duplicated, max ``limit``."""
    seed = seed.strip()
    out: List[str] = [seed]
    seen = {seed.lower()}

    def add(candidate: str) -> None:
        c = candidate.strip("._-")
        if 3 <= len(c) <= 30 and c.lower() not in seen:
            seen.add(c.lower())
            out.append(c)

    toks = _tokens(seed)
    words = [t for t in toks if not t.isdigit()]
    digits = [t for t in toks if t.isdigit()]

    # 1. same words, different separators: john.doe -> john_doe, johndoe
    if len(words) >= 2:
        for sep in _SEPARATORS:
            add(sep.join(words))
        # 2. first-initial forms: jdoe, j.doe
        for sep in ("", ".", "_"):
            add(words[0][0] + sep + words[-1])
        # 3. reversed order: doejohn
        add("".join(reversed(words)))
    # 4. strip trailing digits: jdoe99 -> jdoe
    stripped = re.sub(r"\d+$", "", seed.lower())
    add(stripped)
    if words:
        add("".join(words))
        if digits:                      # keep the number but drop separators: john.doe99 -> johndoe99
            add("".join(words) + digits[-1])
    # 5. common suffixes on the joined base
    base = "".join(words) if words else seed.lower()
    for suf in _SUFFIXES:
        add(f"{base}_{suf}" if not suf.isdigit() else f"{base}{suf}")

    return out[:max(1, limit)]
