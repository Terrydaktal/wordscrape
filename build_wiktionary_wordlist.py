#!/usr/bin/env python3
import argparse
import re
from pathlib import Path

TITLE_WORD_RE = re.compile(r"^[A-Za-z]+$")


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Convert Wiktionary English titles into a lowercase, alphabetic wordlist."
        )
    )
    parser.add_argument(
        "--titles",
        default="wiktionary_english_titles.txt",
        help="Input file containing English page titles (one per line).",
    )
    parser.add_argument(
        "--output",
        default="wiktionary_english_words.txt",
        help="Output wordlist file (one lowercase word per line).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    titles_path = Path(args.titles)
    if not titles_path.is_file():
        raise SystemExit(f"Titles file not found: {titles_path}")

    words = set()
    with titles_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            title = line.strip()
            if not title:
                continue
            if TITLE_WORD_RE.match(title):
                words.add(title.lower())

    output_path = Path(args.output)
    output_path.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"Wrote {len(words)} words to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
