#!/usr/bin/env python3
"""Generate automatic translations for the blog.

Translates posts between Brazilian Portuguese (content/pt/post) and English
(content/en/post), writing the result as DRAFT pages for manual review.

Providers (first one configured wins):
  - DeepL      : set DEEPL_API_KEY (optional: DEEPL_ENDPOINT)
  - LibreTranslate: set LT_URL to a base URL like http://localhost:5000
                   (default: https://translate.argosopentech.com)

Usage:
  python3 scripts/translate.py --dry-run
  python3 scripts/translate.py --to en
  python3 scripts/translate.py --force
"""

import argparse
import json
import os
import re
import shutil
import sys
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONTENT = os.path.join(ROOT, "content")

LANGS = {
    "pt": {"deepl_source": "PT", "deepl_target": "PT-BR", "libre": "pt"},
    "en": {"deepl_source": "EN", "deepl_target": "EN-US", "libre": "en"},
}

FENCE_RE = re.compile(r"`{3,}.*?`{3,}", re.DOTALL)
INLINE_RE = re.compile(r"`[^`\n]+`")
TOKEN_RE = re.compile(r"XCODE(\d+)X", re.IGNORECASE)


def provider():
    return "deepl" if os.environ.get("DEEPL_API_KEY") else "libre"


def _http_json(request, timeout=60):
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        sys.exit(f"translation request failed: {exc.code} {detail}")


def _deepl(text, source, target):
    endpoint = os.environ.get(
        "DEEPL_ENDPOINT", "https://api-free.deepl.com/v2/translate"
    )
    data = urllib.parse.urlencode(
        {
            "auth_key": os.environ["DEEPL_API_KEY"],
            "text": text,
            "source_lang": LANGS[source]["deepl_source"],
            "target_lang": LANGS[target]["deepl_target"],
        }
    ).encode()
    req = urllib.request.Request(endpoint, data=data)
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    return _http_json(req)["translations"][0]["text"]


def _libre(text, source, target):
    base = os.environ.get("LT_URL", "https://translate.argosopentech.com")
    payload = json.dumps(
        {
            "q": text,
            "source": LANGS[source]["libre"],
            "target": LANGS[target]["libre"],
            "format": "text",
        }
    ).encode()
    req = urllib.request.Request(base.rstrip("/") + "/translate", data=payload)
    req.add_header("Content-Type", "application/json")
    api_key = os.environ.get("LT_API_KEY")
    if api_key:
        req.add_header("Authorization", "Bearer " + api_key)
    return _http_json(req)["translatedText"]


def translate_text(text, source, target):
    text = text.strip()
    if not text or source == target:
        return text
    return _deepl(text, source, target) if provider() == "deepl" else _libre(
        text, source, target
    )


def chunk_lines(text, max_chars):
    chunks, current = [], ""
    for line in text.split("\n"):
        if current and len(current) + len(line) + 1 > max_chars:
            chunks.append(current)
            current = line
        else:
            current = current + "\n" + line if current else line
    if current.strip():
        chunks.append(current)
    return chunks


def protect_code(body):
    tokens = []

    def stash(match):
        tokens.append(match.group(0))
        return "XCODE%dX" % (len(tokens) - 1)

    body = FENCE_RE.sub(stash, body)
    body = INLINE_RE.sub(stash, body)
    return body, tokens


def restore_code(text, tokens):
    return TOKEN_RE.sub(lambda m: tokens[int(m.group(1))], text)


def translate_body(body, source, target):
    max_chars = 4500 if provider() == "deepl" else 450
    protected, tokens = protect_code(body)
    out = []
    for chunk in chunk_lines(protected, max_chars):
        out.append(translate_text(chunk, source, target))
    return restore_code("\n".join(out), tokens)


def split_front_matter(text):
    if not text.startswith("---"):
        return [], text
    end = text.find("\n---", 3)
    if end == -1:
        return [], text
    front = text[4:end].split("\n")
    body = text[end + 4 :]
    return front, body


def translate_front_matter(front, source, target):
    out = []
    for line in front:
        m = re.match(r'^(\s*)(title|description):\s*"(.*)"\s*$', line)
        if m:
            val = translate_text(m.group(3), source, target)
            out.append('%s%s: "%s"' % (m.group(1), m.group(2), val))
            continue
        if re.match(r"^\s*draft:\s*\w+\s*$", line):
            out.append("draft: true")
            continue
        out.append(line)
    if not any(re.match(r"^\s*translated:", l) for l in out):
        out.append("translated: true")
    return out


def list_posts(lang):
    base = os.path.join(CONTENT, lang, "post")
    posts = {}
    if not os.path.isdir(base):
        return posts
    for dirpath, _dirs, files in os.walk(base):
        for name in files:
            if name == "_index.md" or not name.endswith(".md"):
                continue
            full = os.path.join(dirpath, name)
            posts[os.path.relpath(full, base)] = full
    return posts


def copy_bundle_assets(src_path, dst_path):
    src_dir = os.path.dirname(src_path)
    dst_dir = os.path.dirname(dst_path)
    if not os.path.isdir(src_dir):
        return
    os.makedirs(dst_dir, exist_ok=True)
    for name in os.listdir(src_dir):
        if name.endswith(".md"):
            continue
        s = os.path.join(src_dir, name)
        if os.path.isfile(s):
            shutil.copy2(s, os.path.join(dst_dir, name))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--to", choices=["en", "pt", "both"], default="both",
                    help="target language(s) to generate")
    ap.add_argument("--force", action="store_true",
                    help="overwrite existing translations")
    ap.add_argument("--dry-run", action="store_true",
                    help="only list what would be translated")
    args = ap.parse_args()

    directions = []
    for source, target in (("pt", "en"), ("en", "pt")):
        if args.to == "both" or args.to == target:
            directions.append((source, target))

    for source, target in directions:
        posts = list_posts(source)
        for rel, src_path in sorted(posts.items()):
            dst_path = os.path.join(CONTENT, target, "post", rel)
            if os.path.exists(dst_path) and not args.force:
                continue
            if args.dry_run:
                print("translate  %s -> %s  (%s)" % (source, target, rel))
                continue

            with open(src_path, encoding="utf-8") as fh:
                raw = fh.read()
            front, body = split_front_matter(raw)
            new_front = translate_front_matter(front, source, target)
            new_body = translate_body(body, source, target)

            os.makedirs(os.path.dirname(dst_path), exist_ok=True)
            with open(dst_path, "w", encoding="utf-8") as fh:
                fh.write("---\n")
                fh.write("\n".join(new_front))
                fh.write("\n---\n\n")
                fh.write(new_body.strip())
                fh.write("\n")
            copy_bundle_assets(src_path, dst_path)
            print("wrote      %s -> %s  (%s)" % (source, target, rel))


if __name__ == "__main__":
    main()
