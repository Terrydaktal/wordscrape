#!/usr/bin/env python3
import argparse
import bz2
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ENGLISH_LINE_RE = re.compile(r"(?m)^\s*==English==\s*$")
CHUNK_SIZE = 8 * 1024 * 1024


def parse_args():
    script_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description=(
            "Download a Wiktionary pages-articles multistream dump and extract titles "
            "whose page text contains an ==English== section."
        )
    )
    parser.add_argument(
        "--dump-url",
        default=(
            "https://dumps.wikimedia.org/enwiktionary/latest/"
            "enwiktionary-latest-pages-articles-multistream.xml.bz2"
        ),
        help="URL for the Wiktionary pages-articles multistream dump.",
    )
    parser.add_argument(
        "--dump-path",
        default=str(script_dir / "enwiktionary-latest-pages-articles-multistream.xml.bz2"),
        help="Path to the dump file (downloaded if missing).",
    )
    parser.add_argument(
        "--output",
        default=str(script_dir / "wiktionary_english_titles.txt"),
        help="Output file for extracted titles.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=50000,
        help="Print progress every N pages (0 to disable).",
    )
    return parser.parse_args()


def download_dump(url, dest_path):
    dest_path = Path(dest_path)
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = dest_path.with_suffix(dest_path.suffix + ".part")
    print(f"Downloading {url} -> {dest_path}", file=sys.stderr)
    with urllib.request.urlopen(url) as response, tmp_path.open("wb") as handle:
        total = response.getheader("Content-Length")
        total_bytes = int(total) if total else None
        downloaded = 0
        while True:
            chunk = response.read(CHUNK_SIZE)
            if not chunk:
                break
            handle.write(chunk)
            downloaded += len(chunk)
            if total_bytes:
                pct = downloaded / total_bytes * 100
                print(
                    f"\rDownloaded {downloaded}/{total_bytes} bytes ({pct:.1f}%)",
                    end="",
                    file=sys.stderr,
                )
        if total_bytes:
            print(file=sys.stderr)
    tmp_path.replace(dest_path)


def _localname(tag):
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def iter_pages(xml_stream):
    context = ET.iterparse(xml_stream, events=("end",))
    for _, elem in context:
        if _localname(elem.tag) != "page":
            continue
        title = None
        revision = None
        for child in elem:
            local = _localname(child.tag)
            if local == "title":
                title = child.text or ""
            elif local == "revision":
                revision = child
        text = None
        if revision is not None:
            for child in revision:
                if _localname(child.tag) == "text":
                    text = child.text or ""
                    break
        yield title, text
        elem.clear()


def open_dump(path):
    path = Path(path)
    if path.suffix == ".bz2":
        return bz2.open(path, "rb")
    return path.open("rb")


def main():
    args = parse_args()
    dump_path = Path(args.dump_path)
    if not dump_path.exists():
        download_dump(args.dump_url, dump_path)

    matched = 0
    processed = 0
    with open_dump(dump_path) as xml_stream, Path(args.output).open(
        "w", encoding="utf-8"
    ) as output:
        for title, text in iter_pages(xml_stream):
            processed += 1
            if text and ENGLISH_LINE_RE.search(text):
                output.write(f"{title}\n")
                matched += 1
            if args.progress_every and processed % args.progress_every == 0:
                print(
                    f"Processed {processed} pages, matched {matched}",
                    file=sys.stderr,
                )
    print(f"Wrote {matched} titles to {args.output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
