#!/usr/bin/env python3
import argparse
import hashlib
import html
import json
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlparse

IMAGE_EXTENSIONS = {".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
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
            classes = {v for k, v in attrs if k == "class"}
            # The class attribute can have multiple space-separated values
            all_classes = set()
            for c in classes: all_classes.update(c.split())
            is_message = "message" in all_classes
            is_text = "text" in all_classes
            self._message_stack.append(is_message)
            self._text_stack.append(is_text)
            if is_message: self._message_depth += 1
            if is_text: self._text_depth += 1
        if self._message_depth > 0 and tag in ("a", "img"):
            attrs_dict = dict(attrs)
            for key in ("href", "src"):
                if key in attrs_dict: self.image_refs.append(attrs_dict[key])

    def handle_endtag(self, tag):
        if tag != "div": return
        if self._message_stack:
            if self._message_stack.pop(): self._message_depth -= 1
        if self._text_stack:
            if self._text_stack.pop(): self._text_depth -= 1

    def handle_data(self, data):
        if self._message_depth > 0 and self._text_depth > 0:
            stripped = data.strip()
            if stripped: self.text_chunks.append(stripped)

def extract_words_from_text(text):
    return {match.lower() for match in WORD_RE.findall(text)}

def resolve_image_paths(image_refs, html_path):
    resolved = []
    for ref in image_refs:
        clean = html.unescape(ref).strip().split("#", 1)[0].split("?", 1)[0]
        parsed = urlparse(clean)
        if parsed.scheme or parsed.netloc: continue
        path = (html_path.parent / Path(unquote(parsed.path))).resolve()
        if "_thumb" in path.stem.lower(): continue
        if path.suffix.lower() in IMAGE_EXTENSIONS and path.is_file(): resolved.append(path)
    return resolved

def load_messages_and_images(chat_dir):
    html_files = sorted(Path(chat_dir).glob("messages*.html"))
    if not html_files: raise FileNotFoundError(f"No messages*.html found in {chat_dir}")
    all_texts, all_images = [], set()
    for html_path in html_files:
        parser = TelegramHTMLParser()
        parser.feed(html_path.read_text(encoding="utf-8"))
        all_texts.extend(parser.text_chunks)
        all_images.update(resolve_image_paths(parser.image_refs, html_path))
    return all_texts, sorted(all_images)

def _ocr_image_words(image_path, lang, min_confidence):
    from PIL import Image
    import pytesseract
    with Image.open(image_path) as image:
        ocr_data = pytesseract.image_to_data(image, lang=lang, output_type=pytesseract.Output.DICT)
    words = set()
    sources = {}
    for raw_text, confidence in zip(ocr_data.get("text", []), ocr_data.get("conf", [])):
        if not raw_text or not raw_text.strip(): continue
        try: conf = float(confidence)
        except: conf = 0
        if min_confidence > 0 and conf < min_confidence: continue
        for match in WORD_RE.findall(raw_text):
            word = match.lower()
            words.add(word)
            sources.setdefault(word, set()).add(str(image_path))
    return words, sources

def ocr_images(image_paths, lang, min_confidence, workers):
    import pytesseract
    ocr_words, word_sources = set(), {}
    with ThreadPoolExecutor(max_workers=max(1, int(workers))) as executor:
        future_map = {executor.submit(_ocr_image_words, p, lang, min_confidence): p for p in image_paths}
        for future in as_completed(future_map):
            try:
                words, sources = future.result()
                ocr_words.update(words)
                for w, paths in sources.items(): word_sources.setdefault(w, set()).update(paths)
            except Exception as e: print(f"Warning: OCR failed for {future_map[future]}: {e}")
    return ocr_words, word_sources

def parse_args():
    script_dir = Path(__file__).parent
    parser = argparse.ArgumentParser(description="Extract deduplicated words from Telegram chat export.")
    parser.add_argument("--chat-dir", default="/home/lewis/Desktop/shit/Telegram Backup/chats/chat_002")
    parser.add_argument("--output", default=str(script_dir / "scrapedwords.txt"))
    parser.add_argument("--skip-ocr", action="store_true")
    parser.add_argument("--ocr-lang", default="eng")
    parser.add_argument("--ocr-min-confidence", type=float, default=60.0)
    parser.add_argument("--ocr-workers", type=int, default=os.cpu_count() or 4)
    parser.add_argument("--ocr-map-output", default=str(script_dir / "ocr_word_map.json"))
    return parser.parse_args()

def main():
    args = parse_args()
    try: texts, images = load_messages_and_images(args.chat_dir)
    except Exception as e: print(e); return 1
    words = set()
    for t in texts: words.update(extract_words_from_text(t))
    ocr_sources = {}
    if not args.skip_ocr and images:
        ocr_words, ocr_sources = ocr_images(images, args.ocr_lang, args.ocr_min_confidence, args.ocr_workers)
        words.update(ocr_words)
    Path(args.output).write_text("\n".join(sorted(words)) + "\n", encoding="utf-8")
    if ocr_sources:
        with Path(args.ocr_map_output).open("w", encoding="utf-8") as f:
            json.dump({w: sorted(list(p)) for w, p in ocr_sources.items()}, f, indent=2)
    print(f"Extracted {len(words)} unique words to {args.output}")

if __name__ == "__main__":
    main()