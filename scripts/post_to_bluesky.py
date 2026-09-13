#!/usr/bin/env python3
"""Post new blog articles to Bluesky.

Scans content/{pt,en}/post for published (non-draft) posts, skips anything
already recorded in the state file, and publishes the rest as Bluesky posts
via the AT Protocol. Since the blog mirrors each article in both languages,
posts are deduped by slug: the default-language (pt) version is preferred,
falling back to whichever language is published first.

Env vars:
  BLUESKY_HANDLE        required (e.g. luizmartins.dev or handle.bsky.social)
  BLUESKY_APP_PASSWORD  required (an app password, not the account password)
  PDSHOST               optional, default https://bsky.social
  BASE_URL              optional, default from hugo.toml's baseURL

Usage:
  python3 scripts/post_to_bluesky.py [--dry-run]
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
STATE_FILE = ROOT / "scripts" / "bluesky-posted.json"

DEFAULT_LANG = "pt"
LANGS = ("pt", "en")
BASE_URL = os.environ.get("BASE_URL", "https://luizmartins.dev").rstrip("/")
PDSHOST = os.environ.get("PDSHOST", "https://bsky.social").rstrip("/")
MAX_LEN = 300


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


def build_record(title, description, url):
    body = f"{title}\n\n{description}" if description else title
    budget = MAX_LEN - (len(url) + 2)
    if len(body) > budget:
        body = body[: max(budget - 1, 0)].rstrip() + "…"
    text = f"{body}\n\n{url}"
    text_bytes = text.encode("utf-8")
    url_bytes = url.encode("utf-8")
    byte_start = len(text_bytes) - len(url_bytes)
    byte_end = len(text_bytes)
    facets = [
        {
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [
                {"$type": "app.bsky.richtext.facet#link", "uri": url}
            ],
        }
    ]
    created_at = datetime.datetime.now(datetime.timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f"
    )[:-3] + "Z"
    return {
        "$type": "app.bsky.feed.post",
        "text": text,
        "createdAt": created_at,
        "facets": facets,
    }


def http_json(url, payload, headers=None):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"Bluesky request to {url} failed: {exc.code} {detail}")


def create_session(handle, app_password):
    resp = http_json(
        f"{PDSHOST}/xrpc/com.atproto.server.createSession",
        {"identifier": handle, "password": app_password},
    )
    return resp["accessJwt"], resp["did"]


def publish(record, access_jwt, did):
    return http_json(
        f"{PDSHOST}/xrpc/com.atproto.repo.createRecord",
        {"repo": did, "collection": "app.bsky.feed.post", "record": record},
        headers={"Authorization": f"Bearer {access_jwt}"},
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
        print("No new posts to publish to Bluesky.")
        return

    pending.sort()

    access_jwt = did = None
    if not args.dry_run:
        handle = os.environ.get("BLUESKY_HANDLE")
        app_password = os.environ.get("BLUESKY_APP_PASSWORD")
        if not handle or not app_password:
            sys.exit("BLUESKY_HANDLE and BLUESKY_APP_PASSWORD must be set.")
        access_jwt, did = create_session(handle, app_password)

    for date, slug, lang, title, description, url in pending:
        record = build_record(title, description, url)
        if args.dry_run:
            print(f"[dry-run] would post ({lang}/{slug}): {record['text']!r}")
            continue
        publish(record, access_jwt, did)
        state[slug] = {"lang": lang, "url": url, "postedAt": record["createdAt"]}
        print(f"Posted to Bluesky: {url}")

    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
