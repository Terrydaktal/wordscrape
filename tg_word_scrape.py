#!/usr/bin/env python3
import argparse
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

try:
    from wordfreq import zipf_frequency
except ImportError:  # pragma: no cover - handled in main
    zipf_frequency = None

IMAGE_EXTENSIONS = {
    ".bmp",
    ".gif",
    ".jpeg",
    ".jpg",
    ".png",
    ".tif",
    ".tiff",
    ".webp",
}
WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
REPEATED_CHAR_RE = re.compile(r"(.)\1\1")


class TelegramHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._message_stack = []
        self._text_stack = []
        self._message_depth = 0
        self._text_depth = 0
        self.text_chunks = []
        self.image_refs = []

    def handle_starttag(self, tag, attrs):
        if tag == "div":
            classes = _attr_classes(attrs)
            is_message = "message" in classes
            is_text = "text" in classes
            self._message_stack.append(is_message)
            self._text_stack.append(is_text)
            if is_message:
                self._message_depth += 1
            if is_text:
                self._text_depth += 1

        if self._message_depth > 0 and tag in ("a", "img"):
            attrs_dict = dict(attrs)
            for key in ("href", "src"):
                if key in attrs_dict:
                    self.image_refs.append(attrs_dict[key])

    def handle_endtag(self, tag):
        if tag != "div":
            return
        if self._message_stack:
            is_message = self._message_stack.pop()
            if is_message:
                self._message_depth -= 1
        if self._text_stack:
            is_text = self._text_stack.pop()
            if is_text:
                self._text_depth -= 1

    def handle_data(self, data):
        if self._message_depth > 0 and self._text_depth > 0:
            stripped = data.strip()
            if stripped:
                self.text_chunks.append(stripped)


def _attr_classes(attrs):
    for key, value in attrs:
        if key == "class":
            return set(value.split())
    return set()


def extract_words_from_text(text):
    return {match.lower() for match in WORD_RE.findall(text)}


def extract_words(texts):
    words = set()
    for text in texts:
        words.update(extract_words_from_text(text))
    return words


def load_wordlists(wordlist_paths):
    wordlist = set()
    for wordlist_path in wordlist_paths:
        with Path(wordlist_path).open("r", encoding="utf-8") as handle:
            for line in handle:
                entry = line.strip()
                if not entry or entry.startswith("#"):
                    continue
                wordlist.add(entry.lower())
    return wordlist


def resolve_image_paths(image_refs, html_path):
    resolved = []
    for ref in image_refs:
        clean = html.unescape(ref).strip()
        if not clean:
            continue
        clean = clean.split("#", 1)[0].split("?", 1)[0]
        parsed = urlparse(clean)
        if parsed.scheme or parsed.netloc:
            continue
        path = Path(unquote(parsed.path))
        if not path.is_absolute():
            path = (html_path.parent / path).resolve()
        if "_thumb" in path.stem.lower():
            continue
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file():
            resolved.append(path)
    return resolved


def load_messages_and_images(chat_dir):
    chat_dir = Path(chat_dir)
    html_files = sorted(chat_dir.glob("messages*.html"))
    if not html_files:
        raise FileNotFoundError(f"No messages*.html found in {chat_dir}")

    all_texts = []
    all_images = set()
    for html_path in html_files:
        parser = TelegramHTMLParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        all_texts.extend(parser.text_chunks)
        all_images.update(resolve_image_paths(parser.image_refs, html_path))
    return all_texts, sorted(all_images)


def _parse_confidence(confidence):
    try:
        return float(confidence)
    except (TypeError, ValueError):
        return None


def _iter_ocr_words(raw_text, *, allow_apostrophes, allow_repeats):
    for match in WORD_RE.findall(raw_text):
        word = match.lower()
        if not allow_apostrophes and "'" in word:
            continue
        if not allow_repeats and REPEATED_CHAR_RE.search(word):
            continue
        yield word


def _ocr_image_words(
    image_path,
    *,
    lang,
    min_confidence,
    allow_apostrophes,
    allow_repeats,
):
    try:
        from PIL import Image
        import pytesseract
    except ImportError as exc:
        raise RuntimeError("Missing OCR dependencies. Install pillow and pytesseract.") from exc

    with Image.open(image_path) as image:
        ocr_data = pytesseract.image_to_data(
            image, lang=lang, output_type=pytesseract.Output.DICT
        )
    words = set()
    sources = {}
    for raw_text, confidence in zip(ocr_data.get("text", []), ocr_data.get("conf", [])):
        if not raw_text or not raw_text.strip():
            continue
        conf_value = _parse_confidence(confidence)
        if min_confidence > 0:
            if conf_value is None or conf_value < min_confidence:
                continue
        for word in _iter_ocr_words(
            raw_text,
            allow_apostrophes=allow_apostrophes,
            allow_repeats=allow_repeats,
        ):
            words.add(word)
            sources.setdefault(word, set()).add(str(image_path))
    return words, sources


def ocr_images(
    image_paths,
    lang,
    *,
    min_confidence,
    allow_apostrophes,
    allow_repeats,
    workers,
):
    try:
        import pytesseract
        from pytesseract import TesseractNotFoundError
    except ImportError as exc:
        raise RuntimeError("Missing OCR dependencies. Install pillow and pytesseract.") from exc

    if "OMP_THREAD_LIMIT" not in os.environ and "OMP_NUM_THREADS" not in os.environ:
        # Avoid oversubscribing CPU when Tesseract uses OpenMP internally.
        os.environ["OMP_THREAD_LIMIT"] = "1"
        os.environ["OMP_NUM_THREADS"] = "1"

    tesseract_cmd = os.environ.get("TESSERACT_CMD")
    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd

    try:
        pytesseract.get_tesseract_version()
    except TesseractNotFoundError as exc:
        raise RuntimeError(
            "tesseract not found on PATH. Install it or set TESSERACT_CMD."
        ) from exc

    ocr_words = set()
    word_sources = {}
    max_workers = max(1, int(workers))
    cpu_count = os.cpu_count() or max_workers
    if max_workers > cpu_count:
        max_workers = cpu_count
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(
                _ocr_image_words,
                image_path,
                lang=lang,
                min_confidence=min_confidence,
                allow_apostrophes=allow_apostrophes,
                allow_repeats=allow_repeats,
            ): image_path
            for image_path in image_paths
        }
        for future in as_completed(future_map):
            image_path = future_map[future]
            try:
                words, sources = future.result()
            except Exception as exc:  # pylint: disable=broad-except
                print(f"Warning: OCR failed for {image_path}: {exc}", file=sys.stderr)
                continue
            ocr_words.update(words)
            for word, paths in sources.items():
                word_sources.setdefault(word, set()).update(paths)
    return ocr_words, word_sources


def rarity_sort(words):
    if zipf_frequency is None:
        raise RuntimeError("Missing dependency: wordfreq.")
    return sorted(words, key=lambda w: (zipf_frequency(w, "en"), w))


def parse_args():
    parser = argparse.ArgumentParser(
        description="Scrape words from a Telegram HTML export and OCR linked images."
    )
    parser.add_argument(
        "--chat-dir",
        default="/home/lewis/Desktop/shit/Telegram Backup/chats/chat_002",
        help="Path to the Telegram chat export directory.",
    )
    parser.add_argument(
        "--output",
        default="words.txt",
        help="Output file for the final word list.",
    )
    parser.add_argument(
        "--skip-ocr",
        action="store_true",
        help="Skip OCR on linked images.",
    )
    parser.add_argument(
        "--ocr-lang",
        default="eng",
        help="Tesseract language code (default: eng).",
    )
    parser.add_argument(
        "--ocr-map-output",
        default="ocr_word_map.json",
        help="Output JSON file mapping OCR words to image paths.",
    )
    parser.add_argument(
        "--ocr-min-confidence",
        type=float,
        default=60.0,
        help="Minimum OCR confidence for a word (0 to disable filtering).",
    )
    parser.add_argument(
        "--ocr-allow-apostrophes",
        action="store_true",
        help="Keep OCR words containing apostrophes.",
    )
    parser.add_argument(
        "--ocr-allow-repeats",
        action="store_true",
        help="Keep OCR words with 3+ repeated letters.",
    )
    parser.add_argument(
        "--ocr-workers",
        type=int,
        default=max(1, os.cpu_count() or 4),
        help="Number of OCR worker threads (default: cpu count).",
    )
    parser.add_argument(
        "--english-wordlist",
        action="append",
        default=[],
        help=(
            "Path to an English wordlist for filtering (one word per line). "
            "Repeat to union multiple lists."
        ),
    )
    parser.add_argument(
        "--wordfreq-allow",
        action="store_true",
        help="Allow words known to wordfreq even if missing from wordlists.",
    )
    parser.add_argument(
        "--discarded-output",
        default="discarded_words.log",
        help="Output file for words discarded by English wordlist filtering.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    chat_dir = Path(args.chat_dir)
    if not chat_dir.is_dir():
        print(f"Chat directory not found: {chat_dir}", file=sys.stderr)
        return 2

    try:
        message_texts, image_paths = load_messages_and_images(chat_dir)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    words = extract_words(message_texts)

    ocr_word_sources = {}
    if not args.skip_ocr and image_paths:
        try:
            ocr_words, ocr_word_sources = ocr_images(
                image_paths,
                args.ocr_lang,
                min_confidence=args.ocr_min_confidence,
                allow_apostrophes=args.ocr_allow_apostrophes,
                allow_repeats=args.ocr_allow_repeats,
                workers=args.ocr_workers,
            )
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        words.update(ocr_words)

    discarded_words = set()
    if args.english_wordlist or args.wordfreq_allow:
        for wordlist_path in args.english_wordlist:
            if not Path(wordlist_path).is_file():
                print(
                    f"English wordlist not found: {wordlist_path}",
                    file=sys.stderr,
                )
                return 2
        allowed = load_wordlists(args.english_wordlist)
        if args.wordfreq_allow:
            if zipf_frequency is None:
                print("Missing dependency: wordfreq.", file=sys.stderr)
                return 2
            for word in words:
                if word in allowed:
                    continue
                if zipf_frequency(word, "en") > 0:
                    allowed.add(word)
        discarded_words = words - allowed
        words &= allowed

    try:
        sorted_words = rarity_sort(words)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    output_path = Path(args.output)
    output_path.write_text("\n".join(sorted_words) + "\n", encoding="utf-8")
    print(f"Wrote {len(sorted_words)} unique words to {output_path}")
    if args.english_wordlist or args.wordfreq_allow:
        discard_path = Path(args.discarded_output)
        discard_path.write_text(
            "\n".join(sorted(discarded_words)) + "\n", encoding="utf-8"
        )
        print(f"Wrote {len(discarded_words)} discarded words to {discard_path}")
    if ocr_word_sources:
        ordered_map = {}
        for word in sorted_words:
            image_paths = ocr_word_sources.get(word)
            if image_paths:
                ordered_map[word] = sorted(image_paths)
        map_path = Path(args.ocr_map_output)
        map_path.write_text(
            json.dumps(ordered_map, indent=2, ensure_ascii=True) + "\n",
            encoding="utf-8",
        )
        print(f"Wrote OCR word map to {map_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
