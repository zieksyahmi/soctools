"""Local report writer (JSON + HTML). Nothing is ever sent anywhere."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

from . import __version__
from .models import Cluster, Edge, LookupResult, Profile

NOTICE = ("CONFIDENTIAL - contains public data gathered about a named subject for an "
          "authorised exercise. Store securely, share only per the Rules of Engagement, "
          "and delete when the engagement ends.")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:60] or "target"


def build_document(target: str, usernames: List[str], dry_run: bool, interrupted: bool,
                   results: List[LookupResult], profiles: List[Profile],
                   edges: List[Edge], clusters: List[Cluster],
                   confidence: List[float], requests_made: int, label_fn) -> Dict:
    return {
        "notice": NOTICE,
        "tool": f"socTools {__version__}",
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "target": target,
        "dry_run": dry_run,
        "partial_run_interrupted": interrupted,
        "usernames_checked": usernames,
        "network_requests_made": requests_made,
        "summary": {
            "lookups": len(results),
            "accounts_found": len(profiles),
            "errors": sum(1 for r in results if r.status == "error"),
        },
        "clusters": [
            {"confidence": c.confidence, "level": c.label,
             "accounts": [
                 {**profiles[m].to_dict(), "account_confidence": round(confidence[m], 3),
                  "account_level": label_fn(confidence[m])} for m in c.members]}
            for c in clusters
        ],
        "evidence": [
            {"a": f"{profiles[e.a].platform}:{profiles[e.a].username}",
             "b": f"{profiles[e.b].platform}:{profiles[e.b].username}",
             "score": e.score, "signals": e.signals}
            for e in sorted(edges, key=lambda e: -e.score) if e.score > 0
        ],
        "lookups": [r.to_dict() for r in results],
    }


def _esc(x) -> str:
    return html.escape(str(x), quote=True)


def render_html(doc: Dict) -> str:
    colour = {"High": "#1a7f37", "Medium": "#b08800", "Low": "#8a8f98"}
    parts = [
        "<!doctype html><html><head><meta charset='utf-8'>",
        f"<title>socTools - {_esc(doc['target'])}</title>",
        "<style>body{font-family:system-ui,sans-serif;max-width:900px;margin:2rem auto;padding:0 1rem}"
        ".warn{background:#fff4ce;border:1px solid #e0c36a;padding:.7rem;border-radius:6px}"
        ".card{border:1px solid #ddd;border-radius:8px;margin:1rem 0;padding:1rem}"
        ".pill{color:#fff;border-radius:99px;padding:.1rem .6rem;font-size:.85rem}"
        "table{border-collapse:collapse;width:100%}td,th{border-bottom:1px solid #eee;"
        "padding:.35rem;text-align:left;font-size:.9rem}</style></head><body>",
        f"<h1>socTools report: {_esc(doc['target'])}</h1>",
        f"<p class='warn'>{_esc(doc['notice'])}</p>",
        f"<p>{_esc(doc['tool'])} &middot; {_esc(doc['generated_utc'])} &middot; "
        f"dry-run: <b>{_esc(doc['dry_run'])}</b> &middot; "
        f"interrupted: <b>{_esc(doc['partial_run_interrupted'])}</b> &middot; "
        f"requests sent: <b>{_esc(doc['network_requests_made'])}</b></p>",
    ]
    if not doc["clusters"]:
        parts.append("<p>No public accounts were found.</p>")
    for i, c in enumerate(doc["clusters"], 1):
        parts.append(f"<div class='card'><h2>Identity cluster {i} "
                     f"<span class='pill' style='background:{colour[c['level']]}'>"
                     f"{_esc(c['level'])} ({c['confidence']:.2f})</span></h2><table>"
                     "<tr><th>Platform</th><th>Username</th><th>Name</th><th>Confidence</th><th>Bio</th></tr>")
        for a in c["accounts"]:
            parts.append(
                f"<tr><td>{_esc(a['platform'])}</td>"
                f"<td><a href='{_esc(a['url'])}' rel='noreferrer noopener'>{_esc(a['username'])}</a></td>"
                f"<td>{_esc(a['display_name'])}</td>"
                f"<td>{_esc(a['account_level'])} ({a['account_confidence']:.2f})</td>"
                f"<td>{_esc(a['bio'])}</td></tr>")
        parts.append("</table></div>")
    if doc["evidence"]:
        parts.append("<h2>Why accounts were linked</h2><table><tr><th>Pair</th><th>Score</th><th>Signals</th></tr>")
        for e in doc["evidence"]:
            parts.append(f"<tr><td>{_esc(e['a'])} &harr; {_esc(e['b'])}</td><td>{e['score']:.2f}</td>"
                         f"<td>{_esc('; '.join(e['signals']))}</td></tr>")
        parts.append("</table>")
    parts.append("</body></html>")
    return "".join(parts)


def save(doc: Dict, output_dir: str) -> Path:
    """Write report.json + report.html into <output_dir>/<target>_<timestamp>/."""
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = Path(output_dir) / f"{_safe(doc['target'])}_{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "report.json").write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    (run_dir / "report.html").write_text(render_html(doc), encoding="utf-8")
    return run_dir
