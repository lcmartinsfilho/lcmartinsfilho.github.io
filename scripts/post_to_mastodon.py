#!/usr/bin/env python3
"""Post new blog articles to Mastodon.

Scans content/{pt,en}/post for published (non-draft) posts, skips anything
already recorded in the state file, and toots the rest. Since the blog
mirrors each article in both languages, posts are deduped by slug: the
default-language (pt) version is preferred, falling back to whichever
language is published first.

Env vars:
  MASTODON_INSTANCE_URL  required (e.g. https://mastodon.social)
  MASTODON_ACCESS_TOKEN  required (a token from an app with write:statuses)
  BASE_URL               optional, default from hugo.toml's baseURL

Usage:
  python3 scripts/post_to_mastodon.py [--dry-run]
"""

import argparse
import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
STATE_FILE = ROOT / "scripts" / "mastodon-posted.json"

DEFAULT_LANG = "pt"
LANGS = ("pt", "en")
BASE_URL = os.environ.get("BASE_URL", "https://luizmartins.dev").rstrip("/")
MAX_LEN = 500
URL_WEIGHT = 23  # Mastodon counts any URL as this many characters, regardless of real length


def split_front_matter(text):
    if not text.startswith("---"):
        return [], text
    end = text.find("\n---", 3)
    if end == -1:
        return [], text
    return text[4:end].split("\n"), text[end + 4:]


def parse_front_matter(lines):
    meta = {}
    for line in lines:
        m = re.match(r'^(\w+):\s*"(.*)"\s*$', line)
        if not m:
            m = re.match(r'^(\w+):\s*(\S.*?)\s*$', line)
        if m:
            meta[m.group(1)] = m.group(2)
    return meta


def collect_posts():
    posts = {}
    for lang in LANGS:
        base = CONTENT / lang / "post"
        if not base.is_dir():
            continue
        for entry in sorted(base.iterdir()):
            if entry.is_dir():
                md, slug = entry / "index.md", entry.name
            elif entry.suffix == ".md" and entry.name != "_index.md":
                md, slug = entry, entry.stem
            else:
                continue
            if not md.exists():
                continue
            front, _ = split_front_matter(md.read_text(encoding="utf-8"))
            posts.setdefault(slug, {})[lang] = parse_front_matter(front)
    return posts


def pick_variant(langs):
    for lang in (DEFAULT_LANG, *[l for l in LANGS if l != DEFAULT_LANG]):
        meta = langs.get(lang)
        if meta and meta.get("draft", "false").lower() != "true":
            return lang, meta
    return None, None


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def build_status(title, description, url):
    body = f"{title}\n\n{description}" if description else title
    budget = MAX_LEN - (URL_WEIGHT + 2)
    if len(body) > budget:
        body = body[: max(budget - 1, 0)].rstrip() + "…"
    return f"{body}\n\n{url}"


def http_json(url, payload, token):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"Mastodon request to {url} failed: {exc.code} {detail}")


def publish(instance_url, token, status, lang):
    return http_json(
        f"{instance_url}/api/v1/statuses",
        {"status": status, "visibility": "public", "language": lang},
        token,
    )


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    posts = collect_posts()
    state = load_state()

    pending = []
    for slug, langs in posts.items():
        if slug in state:
            continue
        lang, meta = pick_variant(langs)
        if not meta:
            continue
        title = meta.get("title", slug)
        description = meta.get("description", "")
        url = f"{BASE_URL}/{lang}/post/{slug}/"
        date = meta.get("date", "")
        pending.append((date, slug, lang, title, description, url))

    if not pending:
        print("No new posts to publish to Mastodon.")
        return

    pending.sort()

    instance_url = token = None
    if not args.dry_run:
        instance_url = os.environ.get("MASTODON_INSTANCE_URL", "").rstrip("/")
        token = os.environ.get("MASTODON_ACCESS_TOKEN")
        if not instance_url or not token:
            sys.exit("MASTODON_INSTANCE_URL and MASTODON_ACCESS_TOKEN must be set.")

    for date, slug, lang, title, description, url in pending:
        status = build_status(title, description, url)
        if args.dry_run:
            print(f"[dry-run] would post ({lang}/{slug}): {status!r}")
            continue
        publish(instance_url, token, status, lang)
        posted_at = datetime.datetime.now(datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.%f"
        )[:-3] + "Z"
        state[slug] = {"lang": lang, "url": url, "postedAt": posted_at}
        print(f"Posted to Mastodon: {url}")

    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
