#!/usr/bin/env python3
"""Cross-post opted-in blog articles to dev.to.

Unlike the Bluesky/Mastodon posters, this is opt-in: only posts whose
front matter `tags` list includes MARKER_TAG get published, since not
every post on this blog is dev/IT content. When both language variants
are published, the English one is preferred (dev.to's audience skews
English-speaking), falling back to Portuguese if only that exists.

Publishes the full article body (with a canonical_url pointing back to
the original post, so dev.to doesn't hurt this site's SEO) rather than
just a title/link teaser.

Env vars:
  DEVTO_API_KEY  required (from https://dev.to/settings/extensions)
  BASE_URL       optional, default from hugo.toml's baseURL

Usage:
  python3 scripts/post_to_devto.py [--dry-run]
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
STATE_FILE = ROOT / "scripts" / "devto-posted.json"

MARKER_TAG = "devto"
LANG_PREFERENCE = ("en", "pt")
LANGS = ("pt", "en")
BASE_URL = os.environ.get("BASE_URL", "https://luizmartins.dev").rstrip("/")
MAX_TAGS = 4


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
        m_list = re.match(r'^(\w+):\s*\[(.*)\]\s*$', line)
        if m_list:
            meta[m_list.group(1)] = re.findall(r'"([^"]*)"', m_list.group(2))
            continue
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
            raw = md.read_text(encoding="utf-8")
            front, body = split_front_matter(raw)
            meta = parse_front_matter(front)
            posts.setdefault(slug, {})[lang] = (meta, body.strip())
    return posts


def has_marker(meta):
    tags = [t.lower() for t in meta.get("tags", [])]
    return MARKER_TAG in tags


def pick_variant(langs):
    for lang in LANG_PREFERENCE:
        entry = langs.get(lang)
        if not entry:
            continue
        meta, _ = entry
        if meta.get("draft", "false").lower() != "true" and has_marker(meta):
            return lang, entry
    return None, None


def load_state():
    if STATE_FILE.exists():
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    return {}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


def sanitize_tag(tag):
    return re.sub(r"[^a-z0-9]", "", tag.lower())


def build_tags(meta):
    raw = [*meta.get("tags", []), *meta.get("categories", [])]
    seen, tags = set(), []
    for tag in raw:
        clean = sanitize_tag(tag)
        if not clean or clean == MARKER_TAG or clean in seen:
            continue
        seen.add(clean)
        tags.append(clean)
        if len(tags) == MAX_TAGS:
            break
    return tags


def absolutize_images(body, post_url):
    def repl(match):
        alt, src = match.group(1), match.group(2)
        if src.startswith(("http://", "https://", "/")):
            return match.group(0)
        return f"![{alt}]({post_url.rstrip('/')}/{src})"

    return re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", repl, body)


def http_json(url, payload, api_key):
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("api-key", api_key)
    # dev.to's Cloudflare front end 403s Python's default urllib User-Agent.
    req.add_header("User-Agent", "lcmartinsfilho.github.io-blog-bot/1.0")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"dev.to request to {url} failed: {exc.code} {detail}")


def publish(api_key, title, description, body_markdown, tags, canonical_url):
    return http_json(
        "https://dev.to/api/articles",
        {
            "article": {
                "title": title,
                "description": description,
                "body_markdown": body_markdown,
                "published": True,
                "tags": tags,
                "canonical_url": canonical_url,
            }
        },
        api_key,
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
        lang, entry = pick_variant(langs)
        if not entry:
            continue
        meta, body = entry
        title = meta.get("title", slug)
        description = meta.get("description", "")
        date = meta.get("date", "")
        url = f"{BASE_URL}/{lang}/post/{slug}/"
        pending.append((date, slug, lang, title, description, body, url))

    if not pending:
        print("No new posts tagged for dev.to.")
        return

    pending.sort()

    api_key = None
    if not args.dry_run:
        api_key = os.environ.get("DEVTO_API_KEY")
        if not api_key:
            sys.exit("DEVTO_API_KEY must be set.")

    for date, slug, lang, title, description, body, url in pending:
        meta = posts[slug][lang][0]
        tags = build_tags(meta)
        body_markdown = absolutize_images(body, url)
        if args.dry_run:
            print(f"[dry-run] would post ({lang}/{slug}) tags={tags} canonical={url}")
            continue
        publish(api_key, title, description, body_markdown, tags, url)
        state[slug] = {"lang": lang, "url": url}
        print(f"Posted to dev.to: {url}")

    if not args.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
