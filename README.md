# socTools

**Cross-Platform Alias & Metadata Correlator**: an educational offensive-OSINT tool that takes a seed username, looks for accounts under that handle (and optionally close variants) on several public platforms, then **scores how likely it is that the discovered accounts belong to the same person**.

> Course project for **IKB31603 Ethical Hacking**, UniKL MIIT. Category 6: *Offensive OSINT (Social Media Footprinter)*.
> **For authorised use only.** Read the [Legal Disclaimer](#legal-disclaimer) and [Rules of Engagement](#rules-of-engagement-roe) first.

---

## Table of contents
1. [What it does](#what-it-does)
2. [Attack category & lifecycle mapping](#attack-category--lifecycle-mapping)
3. [How the correlation works](#how-the-correlation-works)
4. [Installation](#installation)
5. [Usage](#usage)
6. [Output](#output)
7. [Ethical considerations](#ethical-considerations)
8. [Rules of Engagement (RoE)](#rules-of-engagement-roe)
9. [Responsible disclosure](#responsible-disclosure)
10. [Legal disclaimer](#legal-disclaimer)
11. [Limitations](#limitations)
12. [Project layout & tests](#project-layout--tests)
13. [License](#license)

## What it does

A plain "does this username exist?" checker only tells you a handle is taken. socTools goes further:

* **Username permutations**: `john.doe99` also tries `johndoe`, `john_doe`, `jdoe`, `doejohn`, `johndoe_dev`, ... (capped).
* **Public metadata collection** from official, unauthenticated JSON APIs: display name, bio, location, creation date, linked URLs, avatar.
* **Correlation engine**: compares every pair of accounts on independent signals and combines them into a confidence score.
* **Clusters** accounts into probable identities and labels each **High / Medium / Low**, with the evidence listed so a human can verify it.
* **Local JSON + HTML report** with every run clearly labelled and time-stamped.

Platforms (public APIs only): GitHub, GitLab, Codeberg, DEV.to, Hacker News, Reddit.

## Attack category & lifecycle mapping

**Category:** 6 - Offensive OSINT (social media footprinter / alias correlator).

| Lifecycle stage | What socTools does |
|---|---|
| **1. Planning & scoping** | Mandatory legal banner, explicit authorisation prompt naming the subject, request/cap limits, safe default target. |
| **2. Reconnaissance (passive)** | Public-API lookups of the seed handle and its permutations; collection of public profile metadata. |
| **3. Scanning / enumeration** | Concurrent, rate-limited enumeration of platforms; per-lookup status (found / not found / error). |
| **4. Analysis** *(core of the tool)* | Pairwise signal scoring, noisy-OR combination, union-find clustering, High/Medium/Low labelling. |
| **5. Reporting** | JSON + HTML report with evidence for each link between accounts. |
| Exploitation / post-exploitation | **Deliberately not implemented.** The tool never logs in, guesses passwords or touches private data. |

The output feeds the *defensive* purpose of OSINT: showing a client or yourself **how easily separate accounts can be tied together**, so they can reduce that exposure.

## How the correlation works

Each pair of profiles is compared on these signals. Each has a *weight* (maximum evidential strength) multiplied by a 0-1 *strength* for that pair:

| Signal | Weight | Meaning |
|---|---|---|
| `shared_link` | 0.60 | Both point to the same non-generic URL (e.g. a personal site) |
| `cross_reference` | 0.60 | One profile links to / names the other |
| `avatar_match` | 0.55 | Identical avatar bytes (SHA-256), opt-in |
| `bio_similarity` | 0.30 | Fuzzy bio match (character ratio + word overlap), only if >= 60 % |
| `display_name` | 0.25 | Fuzzy name match, only if >= 80 % |
| `location` | 0.10 | Same / contained location string |
| `username_exact` | 0.10 | Identical handle |
| `username_similar` | 0.08 | Close handle |

Scores are combined with a **noisy-OR**: `score = 1 - Π(1 - weightᵢ × strengthᵢ)`.
Many weak hints add up, but one weak hint (e.g. the same common name) can never reach "High" by itself. Pairs scoring >= 0.30 are merged into one identity cluster (union-find). Bands: **High >= 0.60, Medium >= 0.30, Low below.** An account with no corroboration is reported honestly as *Low*, because namesakes are common.

## Installation

Requires **Python 3.9+**. No third-party packages (see `requirements.txt`).

```bash
git clone https://github.com/zieksyahmi/soctools.git
cd soctools
python -m venv .venv && source .venv/bin/activate     # optional
python -m soctools --help
```

## Usage

```bash
# Safe demo: default target "testuser_localhost" (you still must confirm authorisation)
python -m soctools

# Simulate everything with synthetic data - ZERO network traffic
python -m soctools --dry-run

# Preview exactly which requests a real scan would make
python -m soctools --target johndoe --dry-run --permutations

# Real scan of a subject you are authorised to investigate (yourself, a lab account, a client)
python -m soctools --target johndoe --permutations --avatar-hash

# Only some platforms, custom output directory
python -m soctools --target johndoe --platforms github,devto --output ./output
```

| Flag | Purpose |
|---|---|
| `-t, --target` | Seed username (default `testuser_localhost`) |
| `-o, --output` | Report directory (default `./output`, git-ignored) |
| `-n, --dry-run` | Simulate; no network requests |
| `--permutations`, `--max-variants N` | Also check close aliases (capped) |
| `--platforms a,b` | Restrict platforms |
| `--avatar-hash` | Hash avatars **in memory** to compare them (images are never saved) |
| `--delay`, `--max-requests`, `--workers` | Politeness and hard limits |

**Kill switch:** press **Ctrl+C** at any time. Workers stop, queued lookups are cancelled, partial results are correlated and saved (`partial_run_interrupted: true`), and the tool exits with code 130. `SIGTERM` does the same.

## Output

Every run creates `./output/<target>_<timestamp>/` containing `report.json` and `report.html`. Both carry a **CONFIDENTIAL** notice, the tool version, the subject, whether it was a dry-run, and the number of network requests sent.

## Ethical considerations

| Guardrail | Why |
|---|---|
| Startup legal banner + typed confirmation (`Y` / `I AGREE`); EOF counts as *refusal* | Makes authorisation an explicit, conscious act |
| Safe default target and `--dry-run` | An accidental run can never hit a real person |
| Public, unauthenticated APIs only; no logins, no scraping behind walls | Stays within what the platforms intentionally publish |
| Honest `User-Agent`, per-host rate limiting, hard request cap | Avoids abusing services; run is auditable |
| Single-subject scope (one seed + capped variants) | Prevents mass profiling |
| No email/phone/breach lookups, no private-data features | Reduces harm potential |
| Avatars hashed in memory only, never written to disk | Data minimisation |
| Local-only output, git-ignored, labelled CONFIDENTIAL | No exfiltration; clear data handling |
| Confidence labels + listed evidence | Discourages treating a guess as fact; false matches harm real people |

## Rules of Engagement (RoE)

| Item | Rule |
|---|---|
| **Authorised scope** | Only the **single subject named in the written authorisation** (yourself, a consenting person, a lab/test account, or a client's staff member covered by contract). Only the platforms and usernames the authorisation covers. |
| **Time windows** | Only within the dates/hours stated in the authorisation. Default for coursework: lab sessions agreed with the lecturer. Keep scans short; do not schedule or loop runs. |
| **Permitted techniques** | Public-API lookups; username permutation (capped); local correlation of public metadata; local report generation. |
| **Prohibited actions** | Scanning anyone without written authorisation; logging in or using stolen/leaked credentials; bypassing rate limits, blocks or CAPTCHAs; scraping private/protected content; contacting, harassing, doxxing or publishing findings about the subject; uploading results to third-party services; targeting minors; raising `--max-requests`/`--workers` to stress a service. |
| **Emergency stop** | Press **Ctrl+C** (or `kill <pid>` for SIGTERM). Then stop work, secure or delete the `./output/` folder, and notify your lecturer / engagement contact immediately. If a platform blocks you or a service seems degraded, stop and do not retry. |
| **Data retention** | Keep output only for the engagement; delete it afterwards and confirm deletion to the client. |

## Responsible disclosure

socTools results are about **people**, so "disclosure" has two audiences:

* **Who:** first the *authorising party* (client/lecturer), who decides whether the subject is told. Never the public, social media, or forums.
* **When:** deliver the report at the end of the engagement window, within the agreed timeframe (e.g. 5 working days). If you uncover exposure that is urgent (leaked secrets, a credential, a safety risk), report it to the authorising party **immediately**.
* **How:** privately and securely (encrypted channel or password-protected file), including the evidence list and confidence levels, plus remediation advice: separate handles, remove cross-links, review bios/locations, enable privacy settings.
* **Bugs in socTools itself:** open a private security advisory on the GitHub repository (Security → Advisories) or contact the maintainers; allow 90 days before public discussion.
* **Third-party platform issues** found incidentally: report through that platform's official security programme, not publicly.

## Legal disclaimer

This software is provided for **education and authorised security testing only**. In Malaysia, unauthorised access to computer material, and related misuse, may be an offence under the **Computer Crimes Act 1997**; handling personal data can also engage the **Personal Data Protection Act 2010**. Other jurisdictions have comparable laws. The authors accept **no liability** for misuse. You alone are responsible for obtaining written permission and for complying with applicable law and each platform's terms of service. The program displays this notice at every start and will not scan until you confirm.

## Limitations

* Coverage is limited to six platforms with public JSON APIs; many sites need logins or block automation.
* APIs change, rate-limit (GitHub: 60 unauthenticated requests/hour/IP) or block (Reddit often returns HTTP 403/429); such lookups are reported as `error`, not as "not found".
* Correlation is **probabilistic**: High means strong evidence, not proof. Verify manually.
* Same-handle accounts may belong to different people; a missing link does not prove accounts are unrelated.
* Avatar comparison is exact-bytes SHA-256, not perceptual: resized or re-encoded images will not match.
* Dry-run data is synthetic and illustrative only.

## Project layout & tests

```
soctools/
├── soctools/
│   ├── cli.py          # argparse CLI, consent gate, kill switch
│   ├── legal.py        # banner + authorisation prompt
│   ├── permutations.py # username variant generator
│   ├── platforms.py    # public-API adapters + dry-run fixtures
│   ├── net.py          # rate-limited HTTP client / offline dry-run client
│   ├── scanner.py      # concurrent scan engine
│   ├── correlator.py   # signal scoring, noisy-OR, clustering
│   ├── report.py       # JSON + HTML writer
│   └── models.py
├── tests/test_soctools.py
├── requirements.txt  LICENSE  .gitignore  README.md
```

Run the tests: `python -m unittest discover -s tests -v`

## License

[MIT](LICENSE)
