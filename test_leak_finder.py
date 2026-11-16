import base64
import csv
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import quote

import leak_finder

PROJECT_FOLDER = Path(__file__).parent
MARKER = "zebra7731quartz"
PROMPT = "What is the best tea for a cold winter evening zebra7731quartz"
TRACKERS = [
    {"domain": "doubleclick.net", "company": "Google", "category": "advertising"},
    {"domain": "hotjar.com", "company": "Hotjar", "category": "analytics"},
]


def entry(url, headers=None, body=None):
    request = {
        "method": "POST" if body is not None else "GET",
        "url": url,
        "headers": [{"name": k, "value": v} for k, v in (headers or {}).items()],
        "queryString": [],
        "cookies": [],
    }
    if body is not None:
        request["postData"] = {"mimeType": "application/json", "text": body}
    return {"request": request}


def har(*entries):
    return {"log": {"entries": list(entries)}}


def find(*entries, marker=MARKER, prompt=PROMPT, first_party=("chat.example",)):
    return leak_finder.find_leaks(
        har(*entries), marker, first_party=first_party, trackers=TRACKERS, prompt=prompt
    )


class FindingTheMarker(unittest.TestCase):
    def test_plain_marker_in_a_url(self):
        rows = find(entry(f"https://stats.g.doubleclick.net/collect?q={MARKER}"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["site"], "doubleclick.net")
        self.assertEqual(rows[0]["company"], "Google")
        self.assertEqual(rows[0]["category"], "advertising")
        self.assertEqual(rows[0]["what"], "marker")
        self.assertEqual(rows[0]["form"], "plain")
        self.assertEqual(rows[0]["where"], "url")

    def test_url_encoded_sentence(self):
        rows = find(entry("https://stats.g.doubleclick.net/c?dt=" + quote(PROMPT, safe="")))
        self.assertEqual((rows[0]["what"], rows[0]["form"]), ("prompt", "url-encoded"))

    def test_base64_hidden_in_a_longer_string_at_any_position(self):
        for prefix_length in range(7):
            with self.subTest(prefix_length=prefix_length):
                data = b"x" * prefix_length + PROMPT.encode() + b"-end"
                body = json.dumps({"payload": base64.b64encode(data).decode()})
                rows = find(entry("https://in.hotjar.com/e", body=body))
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["form"], "base64")
                self.assertEqual(rows[0]["where"], "body")

    def test_sha256_hash_in_a_header(self):
        digest = hashlib.sha256(PROMPT.encode()).hexdigest()
        rows = find(entry("https://pixel.adnet-example.test/p", headers={"X-User-Id": digest}))
        self.assertEqual((rows[0]["form"], rows[0]["where"]), ("sha256", "header:X-User-Id"))

    def test_hex_encoded_marker(self):
        rows = find(entry(f"https://in.hotjar.com/e?x={MARKER.encode().hex()}"))
        self.assertEqual(rows[0]["form"], "hex")

    def test_nothing_found_when_the_marker_is_absent(self):
        self.assertEqual(find(entry("https://stats.g.doubleclick.net/collect?q=hello")), [])

    def test_a_different_marker_does_not_match(self):
        self.assertEqual(find(entry(f"https://in.hotjar.com/e?q={MARKER}"), marker="otherword99", prompt=None), [])

    def test_a_marker_that_is_too_short_is_refused(self):
        with self.assertRaises(ValueError):
            find(entry("https://in.hotjar.com/e?q=abc"), marker="abc", prompt=None)

    def test_the_marker_must_be_part_of_the_sentence(self):
        with self.assertRaises(ValueError):
            find(entry("https://in.hotjar.com/e"), prompt="a sentence without it")


class WhoCounts(unittest.TestCase):
    def test_the_chatbots_own_addresses_are_not_listed(self):
        rows = find(
            entry(f"https://chat.example/?q={MARKER}"),
            entry(f"https://api.chat.example/send?q={MARKER}"),
        )
        self.assertEqual(rows, [])

    def test_an_extra_first_party_address_can_be_given(self):
        url = f"https://api.chat-company.example/send?q={MARKER}"
        self.assertEqual(len(find(entry(url))), 1)
        self.assertEqual(find(entry(url), first_party=("chat.example", "chat-company.example")), [])

    def test_a_company_not_on_the_list_is_unknown(self):
        rows = find(entry(f"https://pixel.adnet-example.test/p?q={MARKER}"))
        self.assertEqual((rows[0]["company"], rows[0]["category"]), ("Unknown", "unknown"))


class AcceptVersusReject(unittest.TestCase):
    def test_companies_are_compared_across_the_two_logs(self):
        accepted = find(
            entry(f"https://stats.g.doubleclick.net/c?q={MARKER}"),
            entry(f"https://in.hotjar.com/e?q={MARKER}"),
        )
        rejected = find(entry(f"https://in.hotjar.com/e?q={MARKER}"))
        table = {row["site"]: row for row in leak_finder.compare(accepted, rejected)}
        self.assertEqual((table["doubleclick.net"]["after_accept"], table["doubleclick.net"]["after_reject"]), ("yes", "no"))
        self.assertEqual((table["hotjar.com"]["after_accept"], table["hotjar.com"]["after_reject"]), ("yes", "yes"))

    def test_without_a_reject_log_that_column_says_not_tested(self):
        accepted = find(entry(f"https://in.hotjar.com/e?q={MARKER}"))
        self.assertEqual(leak_finder.compare(accepted, None)[0]["after_reject"], "not tested")


class SampleLogs(unittest.TestCase):
    def run_tool(self, folder, *extra):
        out = Path(folder) / "leaks.csv"
        result = subprocess.run(
            [
                sys.executable, "leak_finder.py", MARKER,
                "--site", "chat.example",
                "--prompt", PROMPT,
                "--accept", "data/sample_accept.har",
                "--trackers", "data/known_trackers.csv",
                "--out", str(out), *extra,
            ],
            cwd=PROJECT_FOLDER, capture_output=True, text=True,
        )
        return result, out

    def test_the_sample_logs_give_the_expected_table(self):
        with tempfile.TemporaryDirectory() as folder:
            result, out = self.run_tool(folder, "--reject", "data/sample_reject.har")
            self.assertEqual(result.returncode, 0, result.stderr)
            with out.open(newline="", encoding="utf-8") as file:
                reader = csv.DictReader(file)
                self.assertEqual(
                    reader.fieldnames,
                    ["site", "company", "category", "after_accept", "after_reject", "found_as"],
                )
                rows = {row["site"]: row for row in reader}
        self.assertEqual(sorted(rows), ["adnet-example.test", "doubleclick.net", "hotjar.com"])
        self.assertEqual(sum(row["after_accept"] == "yes" for row in rows.values()), 3)
        self.assertEqual([s for s, r in rows.items() if r["after_reject"] == "yes"], ["hotjar.com"])
        self.assertEqual(rows["adnet-example.test"]["category"], "unknown")
        self.assertNotIn("chat.example", rows)

    def test_a_missing_log_file_gives_a_clear_message(self):
        with tempfile.TemporaryDirectory() as folder:
            result, _ = self.run_tool(folder, "--reject", "data/does_not_exist.har")
            self.assertEqual(result.returncode, 1)
            self.assertIn("Could not read", result.stdout)


if __name__ == "__main__":
    unittest.main(verbosity=2)
