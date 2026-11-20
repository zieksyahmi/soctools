"""Startup legal banner and explicit authorization prompt."""
from __future__ import annotations

import sys
from typing import Callable

BANNER = r"""
==============================================================================
  socTools  -  LEGAL NOTICE & AUTHORIZATION CHECK
==============================================================================
  This tool performs OSINT reconnaissance (public-profile lookups).

  In Malaysia, unauthorised access to, or misuse of, computer material and
  data may be an offence under the COMPUTER CRIMES ACT 1997 (Akta Jenayah
  Komputer 1997). Collecting and profiling personal data may also engage the
  PERSONAL DATA PROTECTION ACT 2010 (PDPA). Equivalent laws apply abroad.

  By continuing you confirm that:
    1. You have EXPLICIT, WRITTEN authorisation covering the subject below
       (or the subject is yourself / a lab account created for testing).
    2. You will stay inside the agreed Rules of Engagement (see README.md).
    3. You accept full responsibility for how the results are used.

  Subject (scope) of this run : {target}
  Mode                        : {mode}
==============================================================================
"""

ACCEPTED = {"y", "yes", "i agree"}


def show_banner(target: str, dry_run: bool, out=sys.stdout) -> None:
    mode = "DRY-RUN (no network requests)" if dry_run else "LIVE (real network requests)"
    out.write(BANNER.format(target=target, mode=mode))


def confirm_authorization(input_fn: Callable[[str], str] = input) -> bool:
    """Return True only if the operator types Y / YES / I AGREE (case-insensitive).

    EOF (e.g. piped stdin with nothing in it) counts as refusal, never consent.
    """
    try:
        answer = input_fn("Type 'Y' or 'I AGREE' to confirm you are authorised: ")
    except EOFError:
        return False
    return answer.strip().lower() in ACCEPTED
