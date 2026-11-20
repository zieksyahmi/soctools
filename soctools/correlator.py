"""Identity-correlation engine (the original logic of socTools).

Question answered: "how likely is it that these two accounts are the same person?"

Method
------
1. Every pair of discovered profiles is compared on independent *signals*
   (shared links, cross-references, identical avatar, fuzzy name / bio /
   username similarity, location). Each signal has a weight (its maximum
   evidential strength) and a 0..1 strength for this pair.
2. Signals are combined with a **noisy-OR**:  score = 1 - prod(1 - weight*strength).
   Independent weak hints add up, but no single weak hint can reach certainty,
   and the score always stays in [0, 1].
3. Pairs scoring >= LINK_THRESHOLD are joined into clusters (union-find).
4. Each account gets a confidence = its strongest edge inside its cluster;
   an uncorroborated account is honestly reported as LOW (names collide!).
"""
from __future__ import annotations

import re
import urllib.parse
from difflib import SequenceMatcher
from typing import Dict, List, Set, Tuple

from .models import Cluster, Edge, Profile

WEIGHTS: Dict[str, float] = {
    "shared_link": 0.60,
    "cross_reference": 0.60,
    "avatar_match": 0.55,
    "bio_similarity": 0.30,
    "display_name": 0.25,
    "location": 0.10,
    "username_exact": 0.10,
    "username_similar": 0.08,
}
LINK_THRESHOLD = 0.30
HIGH, MEDIUM = 0.60, 0.30

# A bare link to one of these sites says nothing ("both link to twitter.com").
GENERIC_HOSTS = {"twitter.com", "x.com", "github.com", "gitlab.com", "facebook.com",
                 "instagram.com", "linkedin.com", "youtube.com", "reddit.com",
                 "codeberg.org", "dev.to", "news.ycombinator.com", "google.com"}


# ----------------------------------------------------------------- text helpers
def norm_text(s: str) -> str:
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower()).strip()


def similarity(a: str, b: str) -> float:
    """Blend of character-level ratio and word-set overlap, robust to reordering."""
    a, b = norm_text(a), norm_text(b)
    if not a or not b:
        return 0.0
    ratio = SequenceMatcher(None, a, b).ratio()
    wa, wb = set(a.split()), set(b.split())
    jaccard = len(wa & wb) / len(wa | wb) if wa | wb else 0.0
    return max(ratio, jaccard)


def norm_url(url: str) -> str:
    """Canonical form: lowercase host without www, no scheme/query/fragment/trailing slash."""
    p = urllib.parse.urlparse(url if "//" in url else "//" + url)
    host = p.netloc.lower().removeprefix("www.")
    return f"{host}{p.path.rstrip('/')}".lower()


def _is_informative(nurl: str) -> bool:
    host, _, path = nurl.partition("/")
    return bool(path) or host not in GENERIC_HOSTS


def _handle(nurl: str) -> Tuple[str, str]:
    host, _, path = nurl.partition("/")
    return host, path.split("/")[0]


# --------------------------------------------------------------------- signals
def compare(a: Profile, b: Profile) -> Edge:
    """Score one pair and list the human-readable reasons."""
    strengths: Dict[str, float] = {}
    notes: List[str] = []

    la = {norm_url(u) for u in a.links}
    lb = {norm_url(u) for u in b.links}
    shared = {u for u in la & lb if _is_informative(u)}
    if shared:
        strengths["shared_link"] = 1.0
        notes.append("both link to " + ", ".join(sorted(shared)))

    pa, pb = norm_url(a.url), norm_url(b.url)
    if pb in la or pa in lb:
        strengths["cross_reference"] = 1.0
        notes.append("one profile links to the other")
    else:
        # e.g. DEV.to lists 'github.com/<name>' -> same handle on GitHub
        ha, hb = _handle(pa), _handle(pb)
        if any(_handle(u) == hb and "/" in u for u in la) or \
           any(_handle(u) == ha and "/" in u for u in lb):
            strengths["cross_reference"] = 1.0
            notes.append("one profile names the other's account")

    if a.avatar_hash and a.avatar_hash == b.avatar_hash:
        strengths["avatar_match"] = 1.0
        notes.append("identical avatar image (sha256)")

    if a.display_name and b.display_name:
        sim = similarity(a.display_name, b.display_name)
        if sim >= 0.8:
            strengths["display_name"] = sim
            notes.append(f"display names similar ({sim:.0%})")

    if len(a.bio) >= 15 and len(b.bio) >= 15:
        sim = similarity(a.bio, b.bio)
        if sim >= 0.6:
            strengths["bio_similarity"] = sim
            notes.append(f"bios similar ({sim:.0%})")

    if a.location and b.location:
        la_, lb_ = norm_text(a.location), norm_text(b.location)
        if la_ and lb_ and (la_ in lb_ or lb_ in la_ or similarity(la_, lb_) >= 0.8):
            strengths["location"] = 1.0
            notes.append("same location")

    ua, ub = a.username.lower(), b.username.lower()
    if ua == ub:
        strengths["username_exact"] = 1.0
        notes.append("identical username")
    else:
        sim = similarity(ua, ub)
        if sim >= 0.75:
            strengths["username_similar"] = sim
            notes.append(f"usernames similar ({sim:.0%})")

    miss = 1.0
    for name, strength in strengths.items():
        miss *= 1.0 - WEIGHTS[name] * strength
    return Edge(-1, -1, round(1.0 - miss, 3), notes)


def label(score: float) -> str:
    return "High" if score >= HIGH else "Medium" if score >= MEDIUM else "Low"


# ------------------------------------------------------------------ clustering
class _UnionFind:
    def __init__(self, n: int):
        self.parent = list(range(n))

    def find(self, x: int) -> int:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: int, b: int) -> None:
        self.parent[self.find(a)] = self.find(b)


def correlate(profiles: List[Profile]) -> Tuple[List[Edge], List[Cluster], List[float]]:
    """Return (all pair edges, clusters sorted by confidence, per-profile confidence)."""
    n = len(profiles)
    edges: List[Edge] = []
    uf = _UnionFind(n)
    for i in range(n):
        for j in range(i + 1, n):
            if profiles[i].platform == profiles[j].platform and profiles[i].username == profiles[j].username:
                continue
            e = compare(profiles[i], profiles[j])
            e.a, e.b = i, j
            edges.append(e)
            if e.score >= LINK_THRESHOLD:
                uf.union(i, j)

    groups: Dict[int, List[int]] = {}
    for i in range(n):
        groups.setdefault(uf.find(i), []).append(i)

    per_profile = [0.0] * n
    for e in edges:
        if uf.find(e.a) == uf.find(e.b):              # only in-cluster evidence counts
            per_profile[e.a] = max(per_profile[e.a], e.score)
            per_profile[e.b] = max(per_profile[e.b], e.score)

    clusters = []
    for members in groups.values():
        conf = sum(per_profile[m] for m in members) / len(members)
        clusters.append(Cluster(sorted(members), round(conf, 3), label(conf)))
    clusters.sort(key=lambda c: (-len(c.members), -c.confidence))
    return edges, clusters, per_profile
