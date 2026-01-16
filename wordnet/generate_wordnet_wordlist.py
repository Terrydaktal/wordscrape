#!/usr/bin/env python3
import argparse
import re
from pathlib import Path


TITLE_WORD_RE = re.compile(r"^[A-Za-z]+$")


def _load_wordnet():
    try:
        from nltk.corpus import wordnet as wn
        wn.synsets("test")
        return wn
    except LookupError:
        import nltk

        nltk.download("wordnet")
        from nltk.corpus import wordnet as wn

        wn.synsets("test")
        return wn


def parse_args():
    script_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(
        description="Generate a lowercase, alphabetic wordlist from WordNet."
    )
    parser.add_argument(
        "--output",
        default=str(script_dir / "wordnet.txt"),
        help="Output wordlist file (one lowercase word per line).",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    wn = _load_wordnet()

    words = set()
    for syn in wn.all_synsets():
        for lemma in syn.lemmas():
            name = lemma.name().replace("_", " ").lower()
            if " " in name:
                continue
            if TITLE_WORD_RE.match(name):
                words.add(name)

    output_path = Path(args.output)
    output_path.write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    print(f"Wrote {len(words)} words to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
