"""Plain data containers shared by every module."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


@dataclass
class Profile:
    """Public metadata of one discovered account."""
    platform: str
    username: str
    url: str
    display_name: str = ""
    bio: str = ""
    location: str = ""
    created_at: str = ""
    avatar_url: str = ""
    avatar_hash: str = ""          # sha256 of avatar bytes; only filled with --avatar-hash
    links: List[str] = field(default_factory=list)   # URLs / handles the profile points to

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class LookupResult:
    """Outcome of asking one platform about one username."""
    platform: str
    username: str
    status: str                    # "found" | "not_found" | "error" | "skipped"
    profile: Optional[Profile] = None
    detail: str = ""

    def to_dict(self) -> Dict:
        return {
            "platform": self.platform,
            "username": self.username,
            "status": self.status,
            "detail": self.detail,
        }


@dataclass
class Edge:
    """Evidence that two profiles belong to the same person."""
    a: int                         # index into the profile list
    b: int
    score: float                   # 0..1
    signals: List[str] = field(default_factory=list)


@dataclass
class Cluster:
    members: List[int]
    confidence: float
    label: str
