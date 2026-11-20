import io
import os
import tempfile
import threading
import unittest
from contextlib import redirect_stdout

from soctools import cli, correlator, legal, permutations, platforms, report
from soctools.models import Profile
from soctools.net import DryRunClient, HttpClient
from soctools.scanner import Scanner


def prof(platform, user, **kw):
    return Profile(platform, user, f"https://{platform.lower()}.test/{user}", **kw)


class PermutationTests(unittest.TestCase):
    def test_seed_first_and_capped(self):
        out = permutations.generate("john.doe", limit=6)
        self.assertEqual(out[0], "john.doe")
        self.assertLessEqual(len(out), 6)
        self.assertEqual(len(out), len({u.lower() for u in out}))

    def test_expected_variants(self):
        out = permutations.generate("john.doe99", limit=30)
        for expected in ("johndoe", "john_doe", "jdoe", "john.doe"):
            self.assertIn(expected, out)


class CorrelatorTests(unittest.TestCase):
    def test_noisy_or_bounds(self):
        a = prof("A", "x", display_name="Alex Tan", bio="security student and ctf player here")
        b = prof("B", "x", display_name="Alex Tan", bio="security student and ctf player here",
                 avatar_hash="h", links=["https://alex.dev"])
        a.avatar_hash = "h"
        a.links = ["https://www.alex.dev/"]
        e = correlator.compare(a, b)
        self.assertTrue(0 < e.score <= 1)
        self.assertGreaterEqual(e.score, correlator.HIGH)

    def test_generic_link_is_ignored(self):
        a = prof("A", "u1", links=["https://twitter.com"])
        b = prof("B", "u2", links=["https://twitter.com/"])
        self.assertEqual(correlator.compare(a, b).score, 0.0)

    def test_same_name_alone_is_not_high(self):
        a = prof("A", "alice1", display_name="John Smith")
        b = prof("B", "bob2", display_name="John Smith")
        self.assertLess(correlator.compare(a, b).score, correlator.HIGH)

    def test_clusters_split_unrelated(self):
        ps = [prof("A", "u", links=["https://me.dev"]), prof("B", "u", links=["https://me.dev"]),
              prof("C", "zzz", bio="completely different words about cats")]
        _, clusters, conf = correlator.correlate(ps)
        self.assertEqual(sorted(len(c.members) for c in clusters), [1, 2])
        self.assertEqual(correlator.label(conf[2]), "Low")


class ParserTests(unittest.TestCase):
    def test_github_parser_and_links(self):
        p = platforms.GitHub().parse("a", {"login": "a", "name": "A", "blog": "https://a.dev",
                                           "twitter_username": "a_t"})
        self.assertIn("https://a.dev", p.links)
        self.assertIn("https://twitter.com/a_t", p.links)

    def test_hn_null_is_not_found(self):
        self.assertIsNone(platforms.HackerNews().parse("x", None))

    def test_html_is_stripped(self):
        self.assertEqual(platforms.clean_text("<p>hi &amp; <b>bye</b></p>"), "hi & bye")

    def test_unknown_platform_rejected(self):
        with self.assertRaises(ValueError):
            platforms.select(["myspace"])


class LegalTests(unittest.TestCase):
    def test_accepts_only_explicit_consent(self):
        self.assertTrue(legal.confirm_authorization(lambda _: "I AGREE"))
        self.assertTrue(legal.confirm_authorization(lambda _: " y "))
        self.assertFalse(legal.confirm_authorization(lambda _: "maybe"))
        self.assertFalse(legal.confirm_authorization(lambda _: ""))

    def test_eof_is_refusal(self):
        def eof(_):
            raise EOFError
        self.assertFalse(legal.confirm_authorization(eof))

    def test_banner_cites_computer_crimes_act(self):
        buf = io.StringIO()
        legal.show_banner("x", True, buf)
        self.assertIn("COMPUTER CRIMES ACT 1997", buf.getvalue())


class SafetyTests(unittest.TestCase):
    def test_request_budget_enforced(self):
        c = HttpClient(threading.Event(), delay=0, max_requests=0)
        status, _, detail = c.get_json("https://example.invalid/")
        self.assertEqual(status, "error")
        self.assertIn("cap", detail)

    def test_dry_run_makes_no_requests(self):
        stop = threading.Event()
        client = DryRunClient(stop, {"bob"}, platforms.dry_run_fixtures, log=lambda m: None)
        Scanner(client, platforms.ALL_PLATFORMS, ["bob"], stop).run()
        self.assertEqual(client.requests_made, 0)

    def test_kill_switch_skips_work(self):
        stop = threading.Event()
        stop.set()
        client = DryRunClient(stop, {"bob"}, platforms.dry_run_fixtures, log=lambda m: None)
        res = Scanner(client, platforms.ALL_PLATFORMS, ["bob"], stop).run()
        self.assertTrue(all(r.status == "skipped" for r in res))


class CliTests(unittest.TestCase):
    def run_cli(self, argv, answer):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = cli.run(argv, input_fn=lambda _: answer)
        return code, buf.getvalue()

    def test_refusal_exits_without_scanning(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli(["--dry-run", "-o", d], "no")
            self.assertEqual(code, 1)
            self.assertEqual(os.listdir(d), [])

    def test_default_target_is_safe(self):
        self.assertEqual(cli.build_parser().parse_args([]).target, "testuser_localhost")

    def test_full_dry_run_writes_reports(self):
        with tempfile.TemporaryDirectory() as d:
            code, out = self.run_cli(["--dry-run", "-o", d], "I AGREE")
            self.assertEqual(code, 0)
            run_dir = os.path.join(d, os.listdir(d)[0])
            self.assertEqual(sorted(os.listdir(run_dir)), ["report.html", "report.json"])
            self.assertIn("HIGH", out)

    def test_bad_target_rejected(self):
        code, _ = self.run_cli(["--target", "a/b"], "I AGREE")
        self.assertEqual(code, 2)


class EdgeCaseQATests(unittest.TestCase):
    """Additional Member 4 QA tests covering edge cases, safety, and report escaping."""

    def test_devto_alias_accepted(self):
        chosen = platforms.select(["github", "devto"])
        self.assertEqual([p.name for p in chosen], ["GitHub", "DEV.to"])

    def test_invalid_numeric_flags_rejected(self):
        for bad_argv in (["--workers", "0"], ["--max-requests", "0"], ["--delay", "-1"]):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.run(bad_argv + ["--dry-run"], input_fn=lambda _: "I AGREE")
            self.assertEqual(code, 2)

    def test_target_spaces_and_length_rejected(self):
        for bad_target in ("john doe", "a" * 65, "user?x=1", "   "):
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.run(["--target", bad_target, "--dry-run"], input_fn=lambda _: "I AGREE")
            self.assertEqual(code, 2)

    def test_empty_and_single_profile_correlate(self):
        edges, clusters, conf = correlator.correlate([])
        self.assertEqual((edges, clusters, conf), ([], [], []))

        p = prof("GitHub", "solo_user", display_name="Solo")
        edges, clusters, conf = correlator.correlate([p])
        self.assertEqual(len(clusters), 1)
        self.assertEqual(clusters[0].label, "Low")
        self.assertEqual(conf[0], 0.0)

    def test_html_report_escapes_xss_payloads(self):
        evil = prof("GitHub", "u1", display_name="<script>alert(1)</script>",
                    bio='"><img src=x onerror=alert(1)>')
        edges, clusters, conf = correlator.correlate([evil])
        doc = report.build_document(
            "<img src=x>", ["u1"], True, False, [], [evil],
            edges, clusters, conf, 0, correlator.label
        )
        rendered = report.render_html(doc)
        self.assertNotIn("<script>alert(1)</script>", rendered)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", rendered)
        self.assertNotIn("<img src=x onerror=alert(1)>", rendered)

    def test_report_filename_sanitization(self):
        safe = report._safe("../../etc/passwd?x=1")
        self.assertNotIn("/", safe)
        self.assertNotIn("\\", safe)
        self.assertNotIn("?", safe)

    def test_full_dry_run_with_permutations_and_avatar_hash(self):
        with tempfile.TemporaryDirectory() as d:
            buf = io.StringIO()
            with redirect_stdout(buf):
                code = cli.run(
                    ["--target", "john.doe99", "--dry-run", "--permutations",
                     "--max-variants", "5", "--avatar-hash", "-o", d],
                    input_fn=lambda _: "Y",
                )
            self.assertEqual(code, 0)
            out = buf.getvalue()
            self.assertIn("identical avatar image (sha256)", out)
            run_dir = os.path.join(d, os.listdir(d)[0])
            self.assertEqual(sorted(os.listdir(run_dir)), ["report.html", "report.json"])

    def test_unreachable_host_returns_error_not_crash(self):
        client = HttpClient(threading.Event(), delay=0, timeout=1.0, max_requests=2)
        status, payload, detail = client.get_json("http://127.0.0.1:1/nonexistent")
        self.assertEqual(status, "error")
        self.assertIsNone(payload)
        self.assertTrue(len(detail) > 0)


if __name__ == "__main__":
    unittest.main()
