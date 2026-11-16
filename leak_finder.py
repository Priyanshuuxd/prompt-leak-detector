"""Find out which outside companies receive text you typed, using a saved network log (HAR file)."""
import argparse
import base64
import csv
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import quote, quote_plus, unquote, urlsplit

PROJECT_FOLDER = Path(__file__).parent
DEFAULT_TRACKERS = PROJECT_FOLDER / "data" / "known_trackers.csv"
DEFAULT_OUTPUT = PROJECT_FOLDER / "output" / "leaks.csv"
MIN_LENGTH = 6  # shorter words could match by accident
COLUMNS = ("site", "company", "category", "after_accept", "after_reject", "found_as")


def site_of(host):
    """Reduce a host like api.chat.example to its site name, chat.example."""
    parts = host.lower().rstrip(".").split(".")
    if len(parts) > 2 and len(parts[-1]) == 2 and parts[-2] in ("co", "com", "org", "ac", "gov", "net"):
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


def find_tracker(domain, trackers):
    """Match a domain itself or one of its subdomains against the tracker list."""
    for tracker in trackers:
        known = tracker["domain"].strip().lower().rstrip(".")
        if domain == known or domain.endswith("." + known):
            return tracker
    return None


def base64_pieces(data):
    """Base64 text that stays the same wherever `data` sits inside a longer value.

    Base64 turns 3 bytes into 4 characters, so the same bytes look different
    depending on how many bytes come before them. We try all 3 positions and
    keep only the characters that do not depend on their neighbours.
    """
    pieces = set()
    for pad in range(3):
        encoded = base64.b64encode(b"\0" * pad + data).decode()
        total = pad + len(data)
        start = (0, 2, 3)[pad]
        stop = (total // 3) * 4 + total % 3
        piece = encoded[start:stop]
        if len(piece) >= MIN_LENGTH:
            pieces.add(piece)
            pieces.add(piece.replace("+", "-").replace("/", "_"))
    return sorted(pieces)


def variants(text):
    """Every form of `text` we search for: (form, needle, must_match_case)."""
    data = text.encode("utf-8")
    found = [("plain", text, False)]
    for encoded in (quote(text, safe=""), quote_plus(text)):
        if encoded != text and ("url-encoded", encoded, False) not in found:
            found.append(("url-encoded", encoded, False))
    found += [("base64", piece, True) for piece in base64_pieces(data)]
    found.append(("hex", data.hex(), False))
    versions = [text] + ([text.strip().lower()] if text.strip().lower() != text else [])
    for name in ("md5", "sha1", "sha256"):
        for version in versions:
            found.append((name, hashlib.new(name, version.encode("utf-8")).hexdigest(), False))
    return found


def search(text, candidates):
    """Return (what, form) for the first candidate found in `text`, or None."""
    for haystack in (text, unquote(text)):
        lowered = haystack.lower()
        for what, form, needle, exact in candidates:
            if (needle in haystack) if exact else (needle.lower() in lowered):
                return what, form
    return None


def request_parts(request):
    """Yield (where, text) for every part of a request that can carry data."""
    yield "url", request.get("url", "")
    for header in request.get("headers", []):
        yield f"header:{header.get('name', '')}", header.get("value", "") or ""
    post = request.get("postData") or {}
    if post.get("text"):
        yield "body", post["text"]
    for param in post.get("params") or []:
        yield "body", param.get("value") or ""


def find_leaks(har, marker, first_party=(), trackers=(), prompt=None):
    """List every outside site whose requests contain the marker (or the whole sentence)."""
    if len(marker) < MIN_LENGTH:
        raise ValueError(f"The marker word needs at least {MIN_LENGTH} characters, so it cannot match by accident.")
    if prompt is not None and marker not in prompt:
        raise ValueError("The marker word must appear in the test sentence.")
    # The whole sentence is the most specific match, so it goes first.
    candidates = []
    if prompt:
        candidates += [("prompt", form, needle, exact) for form, needle, exact in variants(prompt)]
    candidates += [("marker", form, needle, exact) for form, needle, exact in variants(marker)]
    own_sites = {site_of(host) for host in first_party}

    rows, seen = [], set()
    for item in har.get("log", {}).get("entries", []):
        request = item.get("request", {})
        host = urlsplit(request.get("url", "")).hostname
        if not host or site_of(host) in own_sites:
            continue
        tracker = find_tracker(host.lower(), trackers)
        for where, text in request_parts(request):
            hit = search(text, candidates)
            if hit is None:
                continue
            what, form = hit
            key = (site_of(host), where, what, form)
            if key in seen:
                continue
            seen.add(key)
            rows.append({
                "site": site_of(host),
                "company": tracker["company"] if tracker else "Unknown",
                "category": tracker["category"] if tracker else "unknown",
                "where": where,
                "what": what,
                "form": form,
            })
    return sorted(rows, key=lambda row: (row["site"], row["where"]))


def compare(accept_rows, reject_rows):
    """One row per site: did it get the marker after accepting, and after rejecting?"""
    table = {}
    for label, rows in (("accept", accept_rows), ("reject", reject_rows or [])):
        for row in rows:
            entry = table.setdefault(row["site"], {
                "site": row["site"],
                "company": row["company"],
                "category": row["category"],
                "after_accept": "no",
                "after_reject": "no" if reject_rows is not None else "not tested",
                "found_as": set(),
            })
            entry["after_" + label] = "yes"
            entry["found_as"].add(f"{row['what']} as {row['form']} in {row['where']}")
    for entry in table.values():
        entry["found_as"] = "; ".join(sorted(entry["found_as"]))
    return [table[site] for site in sorted(table)]


def read_har(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def read_trackers(path):
    with Path(path).open(encoding="utf-8", newline="") as file:
        return list(csv.DictReader(file))


def host_of(address):
    """Accept chat.example or https://chat.example/ alike."""
    return urlsplit(address).hostname if "://" in address else address.strip("/")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Which outside companies received the word you typed?")
    parser.add_argument("marker", help="the made-up word you typed, e.g. zebra7731quartz")
    parser.add_argument("--site", required=True, help="the chatbot's own address, e.g. chat.example (not counted as a leak)")
    parser.add_argument("--also", action="append", default=[], help="another address owned by the chatbot's company (repeatable)")
    parser.add_argument("--prompt", help="the whole sentence you typed, to also catch it encoded or hashed")
    parser.add_argument("--accept", required=True, help="network log (HAR) saved after accepting cookies")
    parser.add_argument("--reject", help="network log (HAR) saved after rejecting cookies")
    parser.add_argument("--trackers", default=str(DEFAULT_TRACKERS), help="tracker list (CSV with domain, company, category)")
    parser.add_argument("--out", default=str(DEFAULT_OUTPUT), help="where to save the table")
    args = parser.parse_args(argv)

    try:
        accept_har = read_har(args.accept)
        reject_har = read_har(args.reject) if args.reject else None
        trackers = read_trackers(args.trackers)
    except (OSError, json.JSONDecodeError) as error:
        print(f"Could not read a file: {error}")
        return 1

    first_party = [host_of(args.site)] + [host_of(address) for address in args.also]
    try:
        accepted = find_leaks(accept_har, args.marker, first_party, trackers, args.prompt)
        rejected = find_leaks(reject_har, args.marker, first_party, trackers, args.prompt) if reject_har else None
    except ValueError as error:
        print(f"Cannot search: {error}")
        return 1

    table = compare(accepted, rejected)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(table)

    print(f"After accepting cookies: {len(accepted)} request parts carried your word, "
          f"reaching {len({row['site'] for row in accepted})} outside sites.")
    if rejected is not None:
        print(f"After rejecting cookies: {len(rejected)} request parts, "
              f"reaching {len({row['site'] for row in rejected})} outside sites.")
    for row in table:
        print(f"  {row['site']} ({row['company']}, {row['category']}): "
              f"accept={row['after_accept']}, reject={row['after_reject']}, {row['found_as']}")
    if not table:
        print("No outside site received your word in this log. That does not prove none did: "
              "data sent later, from a server, or in a form we do not search for stays invisible here.")
    print(f"Results saved to {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
