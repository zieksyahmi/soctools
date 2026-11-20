"""Command-line interface for socTools."""
from __future__ import annotations

import argparse
import signal
import sys
import textwrap
import threading
from typing import List, Optional

from . import __version__, correlator, legal, permutations, platforms, report
from .models import LookupResult
from .net import DryRunClient, HttpClient
from .scanner import Scanner

SAFE_DEFAULT_TARGET = "testuser_localhost"
_PRINT_LOCK = threading.Lock()


def safe_print(msg: str) -> None:
    """Serialise console output so lines from worker threads never interleave."""
    with _PRINT_LOCK:
        print(msg, flush=True)

EPILOG = textwrap.dedent("""\
    examples:
      %(prog)s                                   safe demo: default target, you will be asked to confirm
      %(prog)s --dry-run                         simulate everything, zero network traffic
      %(prog)s --target johndoe --dry-run        preview the requests a real scan would make
      %(prog)s --target johndoe --permutations   also try close aliases (john.doe, jdoe, ...)
      %(prog)s --target johndoe --platforms github,devto --avatar-hash --output ./output

    Only run against subjects you are authorised in writing to investigate.
    Press Ctrl+C at any time: the scan stops cleanly and partial results are saved.
""")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="soctools",
        description="socTools - cross-platform alias & metadata correlator "
                    "(offensive OSINT, authorised use only).",
        epilog=EPILOG, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-t", "--target", default=SAFE_DEFAULT_TARGET,
                   help=f"seed username to investigate (default: {SAFE_DEFAULT_TARGET})")
    p.add_argument("-o", "--output", default="./output",
                   help="directory for reports (default: ./output, git-ignored)")
    p.add_argument("-n", "--dry-run", action="store_true",
                   help="simulate the scan with synthetic data; makes NO network requests")
    p.add_argument("--permutations", action="store_true",
                   help="also check common variants of the seed username")
    p.add_argument("--max-variants", type=int, default=10,
                   help="cap on usernames checked when --permutations is on (default: 10)")
    p.add_argument("--platforms", help="comma-separated subset, e.g. github,devto "
                   f"(available: {', '.join(x.name.lower() for x in platforms.ALL_PLATFORMS)})")
    p.add_argument("--avatar-hash", action="store_true",
                   help="download avatars IN MEMORY to compare their SHA-256 (images are not saved)")
    p.add_argument("--delay", type=float, default=1.0,
                   help="minimum seconds between requests to the same host (default: 1.0)")
    p.add_argument("--max-requests", type=int, default=60,
                   help="hard cap on total network requests (default: 60)")
    p.add_argument("--workers", type=int, default=4, help="concurrent workers (default: 4)")
    p.add_argument("-V", "--version", action="version", version=f"soctools {__version__}")
    return p


def _print_summary(profiles, clusters, confidence, edges) -> None:
    print("\n=== Results " + "=" * 58)
    if not profiles:
        print("No public accounts found.")
        return
    for i, c in enumerate(clusters, 1):
        print(f"\nCluster {i}: {c.label.upper()} confidence ({c.confidence:.2f}), "
              f"{len(c.members)} account(s)")
        for m in c.members:
            p = profiles[m]
            print(f"  - {p.platform:<10} {p.username:<22} {correlator.label(confidence[m]):<6} "
                  f"({confidence[m]:.2f})  {p.url}")
        reasons = {s for e in edges if e.a in c.members and e.b in c.members
                   and e.score >= correlator.LINK_THRESHOLD for s in e.signals}
        for r in sorted(reasons):
            print(f"      evidence: {r}")


def run(argv: Optional[List[str]] = None, input_fn=input) -> int:
    args = build_parser().parse_args(argv)
    target = args.target.strip()
    if not target or len(target) > 64 or any(ch.isspace() or ch in "/\\?#" for ch in target):
        print("error: --target must be a single username (no spaces or / ? #).", file=sys.stderr)
        return 2
    if args.max_requests < 1 or args.workers < 1 or args.delay < 0:
        print("error: --max-requests/--workers must be >= 1 and --delay >= 0.", file=sys.stderr)
        return 2
    try:
        chosen = platforms.select(args.platforms.split(",") if args.platforms else None)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    # --- legal gate -------------------------------------------------------
    legal.show_banner(target, args.dry_run)
    if not legal.confirm_authorization(input_fn):
        print("Authorisation not confirmed. Exiting without scanning.")
        return 1

    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())    # polite kill from another shell

    usernames = (permutations.generate(target, args.max_variants)
                 if args.permutations else [target])
    print(f"\nScope: {len(usernames)} username(s) x {len(chosen)} platform(s) "
          f"= {len(usernames) * len(chosen)} lookup(s). Ctrl+C to abort safely.\n")

    client = (DryRunClient(stop, {target}, platforms.dry_run_fixtures)
              if args.dry_run else
              HttpClient(stop, args.delay, max_requests=args.max_requests))
    if args.dry_run:
        client.log = safe_print

    def progress(r: LookupResult) -> None:
        mark = {"found": "+", "not_found": "-", "error": "!", "skipped": "."}[r.status]
        safe_print(f"[{mark}] {r.platform:<10} {r.username:<22} {r.status} {r.detail}".rstrip())

    scanner = Scanner(client, chosen, usernames, stop, args.workers, args.avatar_hash, progress)
    interrupted = False
    try:
        scanner.run()
        interrupted = scanner.interrupted
    except KeyboardInterrupt:                    # interrupted outside the pool loop
        interrupted = True
        stop.set()
    if interrupted:
        print("\n[!] Interrupted - stopping workers and saving partial results...")

    profiles = [r.profile for r in scanner.results if r.status == "found" and r.profile]
    edges, clusters, confidence = correlator.correlate(profiles)
    _print_summary(profiles, clusters, confidence, edges)

    doc = report.build_document(target, usernames, args.dry_run, interrupted, scanner.results,
                                profiles, edges, clusters, confidence,
                                client.requests_made, correlator.label)
    out_dir = report.save(doc, args.output)
    print(f"\nReports saved locally to: {out_dir}/ (report.json, report.html)")
    if args.dry_run:
        print("Dry-run: all data above is synthetic demo data.")
    return 130 if interrupted else 0


def main() -> None:
    try:
        sys.exit(run())
    except KeyboardInterrupt:                    # e.g. Ctrl+C at the consent prompt
        print("\nAborted by user. Nothing was scanned.")
        sys.exit(130)


if __name__ == "__main__":
    main()
