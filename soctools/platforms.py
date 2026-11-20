"""Platform adapters: one tiny class per site that exposes a *public JSON API*.

Only documented, unauthenticated, public endpoints are used. No logins, no
HTML scraping behind walls, no private data. Each adapter turns the site's
JSON into the common :class:`Profile` model.
"""
from __future__ import annotations

import html
import re
import urllib.parse
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Set

from .models import Profile

_URL_RE = re.compile(r"https?://[^\s<>\"')\]]+", re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def clean_text(value: Any) -> str:
    """Strip HTML tags/entities and collapse whitespace."""
    if not value:
        return ""
    text = html.unescape(_TAG_RE.sub(" ", str(value)))
    return re.sub(r"\s+", " ", text).strip()


def extract_urls(*chunks: Any) -> List[str]:
    """Collect unique URLs from free text / website fields, preserving order."""
    found: List[str] = []
    for chunk in chunks:
        if not chunk:
            continue
        text = html.unescape(str(chunk))
        candidates = _URL_RE.findall(text)
        if not candidates and re.match(r"^[\w.-]+\.[a-z]{2,}(/\S*)?$", text.strip(), re.I):
            candidates = ["https://" + text.strip()]       # bare 'example.com'
        for url in candidates:
            url = url.rstrip(".,;")
            if url not in found:
                found.append(url)
    return found


def _iso_from_unix(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError, OSError):
        return ""


def _date(value: Any) -> str:
    return str(value)[:10] if value else ""


class Platform:
    name = ""

    def api_url(self, username: str) -> str: ...
    def profile_url(self, username: str) -> str: ...
    def parse(self, username: str, data: Any) -> Optional[Profile]: ...


class GitHub(Platform):
    name = "GitHub"

    def api_url(self, u): return f"https://api.github.com/users/{urllib.parse.quote(u)}"
    def profile_url(self, u): return f"https://github.com/{u}"

    def parse(self, u, d):
        if not isinstance(d, dict) or not d.get("login"):
            return None
        links = extract_urls(d.get("blog"), d.get("bio"))
        if d.get("twitter_username"):
            links.append(f"https://twitter.com/{d['twitter_username']}")
        return Profile(self.name, d["login"], d.get("html_url") or self.profile_url(u),
                       clean_text(d.get("name")), clean_text(d.get("bio")),
                       clean_text(d.get("location")), _date(d.get("created_at")),
                       d.get("avatar_url") or "", links=links)


class GitLab(Platform):
    name = "GitLab"

    def api_url(self, u): return f"https://gitlab.com/api/v4/users?username={urllib.parse.quote(u)}"
    def profile_url(self, u): return f"https://gitlab.com/{u}"

    def parse(self, u, d):
        if not isinstance(d, list) or not d or not isinstance(d[0], dict):
            return None
        p = d[0]
        return Profile(self.name, p.get("username", u), p.get("web_url") or self.profile_url(u),
                       clean_text(p.get("name")), clean_text(p.get("bio")),
                       clean_text(p.get("location")), _date(p.get("created_at")),
                       p.get("avatar_url") or "",
                       links=extract_urls(p.get("website_url"), p.get("bio")))


class Codeberg(Platform):
    name = "Codeberg"

    def api_url(self, u): return f"https://codeberg.org/api/v1/users/{urllib.parse.quote(u)}"
    def profile_url(self, u): return f"https://codeberg.org/{u}"

    def parse(self, u, d):
        if not isinstance(d, dict) or not d.get("login"):
            return None
        return Profile(self.name, d["login"], d.get("html_url") or self.profile_url(u),
                       clean_text(d.get("full_name")), clean_text(d.get("description")),
                       clean_text(d.get("location")), _date(d.get("created")),
                       d.get("avatar_url") or "",
                       links=extract_urls(d.get("website"), d.get("description")))


class DevTo(Platform):
    name = "DEV.to"

    def api_url(self, u): return f"https://dev.to/api/users/by_username?url={urllib.parse.quote(u)}"
    def profile_url(self, u): return f"https://dev.to/{u}"

    def parse(self, u, d):
        if not isinstance(d, dict) or not d.get("username"):
            return None
        links = extract_urls(d.get("website_url"), d.get("summary"))
        if d.get("github_username"):
            links.append(f"https://github.com/{d['github_username']}")
        if d.get("twitter_username"):
            links.append(f"https://twitter.com/{d['twitter_username']}")
        return Profile(self.name, d["username"], self.profile_url(d["username"]),
                       clean_text(d.get("name")), clean_text(d.get("summary")),
                       clean_text(d.get("location")), clean_text(d.get("joined_at"))[:10],
                       d.get("profile_image") or "", links=links)


class HackerNews(Platform):
    name = "HackerNews"

    def api_url(self, u): return f"https://hacker-news.firebaseio.com/v0/user/{urllib.parse.quote(u)}.json"
    def profile_url(self, u): return f"https://news.ycombinator.com/user?id={u}"

    def parse(self, u, d):
        if not isinstance(d, dict) or not d.get("id"):      # API returns JSON null if absent
            return None
        return Profile(self.name, d["id"], self.profile_url(d["id"]), "",
                       clean_text(d.get("about")), "", _iso_from_unix(d.get("created")),
                       links=extract_urls(d.get("about")))


class Reddit(Platform):
    name = "Reddit"

    def api_url(self, u): return f"https://www.reddit.com/user/{urllib.parse.quote(u)}/about.json"
    def profile_url(self, u): return f"https://www.reddit.com/user/{u}"

    def parse(self, u, d):
        data = d.get("data") if isinstance(d, dict) else None
        if not isinstance(data, dict) or not data.get("name"):
            return None
        sub = data.get("subreddit") or {}
        bio = clean_text(sub.get("public_description"))
        return Profile(self.name, data["name"], self.profile_url(data["name"]),
                       clean_text(sub.get("title")), bio, "",
                       _iso_from_unix(data.get("created_utc")),
                       (data.get("icon_img") or "").split("?")[0],
                       links=extract_urls(bio))


ALL_PLATFORMS: List[Platform] = [GitHub(), GitLab(), Codeberg(), DevTo(), HackerNews(), Reddit()]
BY_NAME: Dict[str, Platform] = {p.name.lower(): p for p in ALL_PLATFORMS}
BY_NAME["devto"] = BY_NAME["dev.to"]


def select(names: Optional[List[str]]) -> List[Platform]:
    if not names:
        return list(ALL_PLATFORMS)
    chosen = []
    for n in names:
        key = n.strip().lower()
        if key not in BY_NAME:
            raise ValueError(f"unknown platform '{n}'. Choices: {', '.join(p.name for p in ALL_PLATFORMS)}")
        chosen.append(BY_NAME[key])
    return chosen


# --------------------------------------------------------------------------
# Synthetic fixtures for --dry-run.  Everything below is invented demo data
# about a fictional person; it never describes a real individual.
# --------------------------------------------------------------------------
def dry_run_fixtures(url: str, known: Set[str]) -> Optional[Any]:
    parsed = urllib.parse.urlparse(url)
    host = parsed.netloc
    last = urllib.parse.unquote(parsed.path.rstrip("/").split("/")[-1])
    user = re.sub(r"\.json$", "", last)
    if "username=" in parsed.query:
        user = urllib.parse.parse_qs(parsed.query)["username"][0]
    elif "url=" in parsed.query:
        user = urllib.parse.parse_qs(parsed.query)["url"][0]
    if user.lower() not in known:
        return None
    site = "https://alextan.example.com"
    shared_bio = "Security student and CTF player building small OSINT tools"
    if host == "api.github.com":
        return {"login": user, "html_url": f"https://github.com/{user}", "name": "Alex Tan",
                "bio": shared_bio, "blog": site, "location": "Kuala Lumpur, Malaysia",
                "created_at": "2019-03-02T08:00:00Z",
                "avatar_url": "https://avatars.example.com/shared-avatar.png",
                "twitter_username": "alextan_sec"}
    if host == "codeberg.org":
        return {"login": user, "html_url": f"https://codeberg.org/{user}", "full_name": "Alex Tan",
                "description": shared_bio + ".", "website": site, "location": "Kuala Lumpur",
                "created": "2021-07-15T10:00:00Z",
                "avatar_url": "https://codeberg.example.com/shared-avatar.png"}
    if host == "dev.to":
        return {"username": user, "name": "Alex Tan", "summary": "Writing about CTFs and security labs",
                "github_username": user, "website_url": site, "location": "Kuala Lumpur, MY",
                "joined_at": "2022-01-20T00:00:00Z", "profile_image": "https://dev.example.com/a.png"}
    if host == "gitlab.com":
        return [{"username": user, "web_url": f"https://gitlab.com/{user}", "name": "A. Tan",
                 "created_at": "2020-05-01T00:00:00Z", "avatar_url": "https://gitlab.example.com/g.png"}]
    if host == "www.reddit.com":
        return {"data": {"name": user, "created_utc": 1500000000,
                         "subreddit": {"title": "", "public_description": "Cats, retro gaming, coffee."},
                         "icon_img": "https://reddit.example.com/r.png"}}
    return None          # HackerNews: simulate "no such user"
