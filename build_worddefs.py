#!/usr/bin/env python3
import argparse
import bz2
import html
import re
import xml.etree.ElementTree as ET
from pathlib import Path


HEADING_RE = re.compile(r"^(=+)\s*(.+?)\s*\1\s*$")
DEF_LINE_RE = re.compile(r"^(#+)\s*(.*)")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
EXTERNAL_LINK_RE = re.compile(r"\[(https?://[^\s\]]+)\s+([^\]]+)\]")
EXTERNAL_LINK_SIMPLE_RE = re.compile(r"\[(https?://[^\s\]]+)\]")
WIKILINK_PIPED_RE = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
WIKILINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
TAG_RE = re.compile(r"<[^>]+>")
HAS_ALNUM_RE = re.compile(r"[A-Za-z0-9]")

LABEL_TEMPLATES = {"lb", "lbl", "label", "labels", "tag", "tags"}
LINK_TEMPLATES = {"l", "link", "m", "mention", "w", "wp", "wikipedia"}
DEFINITION_TEMPLATES = {
    "abbreviation of": "Abbreviation of {term}",
    "abbr of": "Abbreviation of {term}",
    "acronym of": "Acronym of {term}",
    "alternative form of": "Alternative form of {term}",
    "alt form": "Alternative form of {term}",
    "alt form of": "Alternative form of {term}",
    "alternative spelling of": "Alternative spelling of {term}",
    "alt spelling of": "Alternative spelling of {term}",
    "alt sp": "Alternative spelling of {term}",
    "alt sp of": "Alternative spelling of {term}",
    "altsp": "Alternative spelling of {term}",
    "alt spell": "Alternative spelling of {term}",
    "alt spell of": "Alternative spelling of {term}",
    "alternative case form of": "Alternative case form of {term}",
    "alternative letter-case of": "Alternative letter-case of {term}",
    "alternative capitalization of": "Alternative capitalization of {term}",
    "alt case": "Alternative case form of {term}",
    "altform": "Alternative form of {term}",
    "contraction of": "Contraction of {term}",
    "clipping of": "Clipping of {term}",
    "comparative of": "Comparative of {term}",
    "superlative of": "Superlative of {term}",
    "initialism of": "Initialism of {term}",
    "init of": "Initialism of {term}",
    "misspelling of": "Misspelling of {term}",
    "plural of": "Plural of {term}",
    "plural form of": "Plural of {term}",
    "past tense of": "Past tense of {term}",
    "past participle of": "Past participle of {term}",
    "present participle of": "Present participle of {term}",
    "simple past of": "Simple past of {term}",
    "obs form": "Obsolete form of {term}",
    "obs sp": "Obsolete spelling of {term}",
    "obs sp of": "Obsolete spelling of {term}",
    "stand sp": "Standard spelling of {term}",
    "standard sp": "Standard spelling of {term}",
    "pron sp": "Pronunciation spelling of {term}",
    "ellipsis of": "Ellipsis of {term}",
    "only used in": "Only used in {term}",
    "short for": "Short for {term}",
    "form of": "Form of {term}",
    "inflection of": "Inflection of {term}",
}
NAME_TEMPLATES = {
    "surname": "Surname",
    "given name": "Given name",
}
PLACE_TEMPLATES = {"place"}
QUALIFIER_TEMPLATES = {"q", "qual", "qualifier"}
USAGE_TEMPLATES = {"ux", "uxi", "uxa"}
QUOTE_TEMPLATES = {
    "quote-book",
    "quote-journal",
    "quote-text",
    "quote-web",
    "quote-av",
    "quote-song",
    "quote-hansard",
}
NON_GLOSS_TEMPLATES = {"non-gloss", "ng", "ngd"}
EMPTY_TEMPLATES = {"senseid", "sid"}
PLACE_PREFIXES = ("c", "r", "s", "co", "par", "dist", "cc")
PLACE_INLINE_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(prefix) for prefix in PLACE_PREFIXES) + r")/([^\s,;]+)",
    re.IGNORECASE,
)
PLACE_NAMED_FIELDS = {
    "caplc": "capital",
    "capital": "capital",
    "official": "official name",
    "full": "full name",
    "short": "short name",
    "abbr": "abbreviation",
    "seat": "seat",
}


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Extract English Wiktionary definitions for words in wordfreqs.txt."
        )
    )
    parser.add_argument(
        "--dump",
        default="enwiktionary-latest-pages-articles-multistream.xml.bz2",
        help="Path to the Wiktionary pages-articles XML dump (.bz2).",
    )
    parser.add_argument(
        "--wordfreqs",
        default="wordfreqs.txt",
        help="Path to the wordfreqs output file.",
    )
    parser.add_argument(
        "--output",
        default="worddefs.txt",
        help="Output file for word definitions.",
    )
    return parser.parse_args()


def load_wordfreq_words(wordfreq_path):
    words = []
    with Path(wordfreq_path).open("r", encoding="utf-8") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped or stripped.startswith("WORD") or stripped.startswith("-"):
                continue
            words.append(stripped.split()[0])
    return words


def _extract_template(text, start):
    depth = 0
    idx = start
    while idx < len(text):
        if text.startswith("{{", idx):
            depth += 1
            idx += 2
            continue
        if text.startswith("}}", idx) and depth:
            depth -= 1
            idx += 2
            if depth == 0:
                return idx, text[start + 2 : idx - 2]
            continue
        idx += 1
    return None, None


def _split_template_parts(content):
    parts = []
    current = []
    depth = 0
    idx = 0
    while idx < len(content):
        if content.startswith("{{", idx):
            depth += 1
            current.append("{{")
            idx += 2
            continue
        if content.startswith("}}", idx) and depth:
            depth -= 1
            current.append("}}")
            idx += 2
            continue
        if content[idx] == "|" and depth == 0:
            parts.append("".join(current).strip())
            current = []
            idx += 1
            continue
        current.append(content[idx])
        idx += 1
    parts.append("".join(current).strip())
    return [part for part in parts if part]


def _strip_templates(text):
    result = []
    depth = 0
    idx = 0
    while idx < len(text):
        if text.startswith("{{", idx):
            depth += 1
            idx += 2
            continue
        if depth and text.startswith("}}", idx):
            depth -= 1
            idx += 2
            continue
        if depth == 0:
            result.append(text[idx])
        idx += 1
    return "".join(result)


def _strip_wiki_prefix(text):
    if ":" not in text:
        return text
    prefix, rest = text.split(":", 1)
    if prefix.lower() in {"w", "wikipedia", "wiktionary", "s", "quote", "commons"}:
        return rest
    return text


def _parse_template(content):
    parts = _split_template_parts(content)
    if not parts:
        return "", [], {}
    name = parts[0].strip().lower()
    positional = []
    named = {}
    for param in parts[1:]:
        if not param:
            continue
        if "=" in param:
            key, value = param.split("=", 1)
            key = key.strip().lower()
            value = _expand_templates(value).strip()
            if value:
                named[key] = value
        else:
            value = _expand_templates(param).strip()
            if value:
                positional.append(value)
    positional = [
        param
        for param in positional
        if param.lower() not in {"en", "eng", "english"}
    ]
    positional = [_strip_wiki_prefix(param) for param in positional]
    named = {key: _strip_wiki_prefix(value) for key, value in named.items() if value}
    return name, positional, named


def _normalize_place_param(param):
    param = param.replace("<<", "").replace(">>", "")
    param = param.strip()
    if param.startswith("@"):
        param = param[1:].strip()
    lower = param.lower()
    if lower.startswith("abbrev of:"):
        param = f"abbreviation of {param.split(':', 1)[1].strip()}"
    elif lower.startswith("abbrev of "):
        param = f"abbreviation of {param[9:].strip()}"
    elif lower.startswith("abbr of:"):
        param = f"abbreviation of {param.split(':', 1)[1].strip()}"
    elif lower.startswith("abbr of "):
        param = f"abbreviation of {param[7:].strip()}"
    lower = param.lower()
    for prefix in PLACE_PREFIXES:
        token = prefix + "/"
        if lower.startswith(token):
            value = param[len(token) :].strip()
            if value:
                return f"in {value.replace('_', ' ')}"
    param = PLACE_INLINE_RE.sub(lambda match: match.group(1), param)
    param = param.replace("/", " ")
    param = param.replace("_", " ")
    param = re.sub(r"\s+", " ", param).strip()
    return param


def _join_place_parts(parts):
    if not parts:
        return ""
    combined = []
    for part in parts:
        if part == ";":
            if combined:
                combined[-1] = combined[-1].rstrip()
            combined.append(";")
        else:
            combined.append(part)
    text = " ".join(combined)
    text = text.replace(" ;", ";")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _render_place_template(params, named):
    parts = []
    for param in params:
        if not param:
            continue
        if param.strip() == ";":
            parts.append(";")
            continue
        normalized = _normalize_place_param(param)
        if normalized:
            parts.append(normalized)
    text = _join_place_parts(parts)
    details = []
    for key, label in PLACE_NAMED_FIELDS.items():
        value = named.get(key)
        if value:
            cleaned = value.replace("_", " ").replace("<<", "").replace(">>", "").strip()
            if cleaned:
                details.append(f"{label}: {cleaned}")
    if details:
        details_text = "; ".join(details)
        if text:
            text = f"{text}; {details_text}"
        else:
            text = details_text
    return text


def _render_name_template(label, params, named):
    details = []
    if params:
        details.extend(params)
    origin = named.get("from") or named.get("origin")
    if origin:
        details.append(f"from {origin}")
    meaning = named.get("meaning")
    if meaning:
        details.append(f"meaning {meaning}")
    if details:
        return f"{label} ({', '.join(details)})"
    return label


def _render_qualifier_template(params):
    if not params:
        return ""
    return f"({', '.join(params)})"


def _render_usage_template(params, named):
    if params:
        return params[0]
    text = named.get("text") or named.get("passage") or named.get("quote")
    return text or ""


def _render_quote_template(params, named):
    text = named.get("text") or named.get("passage") or named.get("quote")
    if text:
        return text
    return ""


def _render_template(content):
    name, params, named = _parse_template(content)
    if not name:
        return ""
    if name in LABEL_TEMPLATES:
        if params:
            return f"({', '.join(params)})"
        return ""
    if name in LINK_TEMPLATES:
        return params[0] if params else ""
    if name in EMPTY_TEMPLATES:
        return ""
    if name in QUALIFIER_TEMPLATES:
        return _render_qualifier_template(params)
    if name in NAME_TEMPLATES:
        return _render_name_template(NAME_TEMPLATES[name], params, named)
    if name in PLACE_TEMPLATES:
        return _render_place_template(params, named)
    if name in NON_GLOSS_TEMPLATES:
        return params[0] if params else ""
    if name in USAGE_TEMPLATES:
        return _render_usage_template(params, named)
    if name in QUOTE_TEMPLATES:
        return _render_quote_template(params, named)
    if name in DEFINITION_TEMPLATES:
        if params:
            text = DEFINITION_TEMPLATES[name].format(term=params[0])
            extras = [param for param in params[1:] if param]
            if extras:
                text = f"{text} ({'; '.join(extras)})"
            return text
        return ""
    if name.endswith(" of") and params:
        return f"{name.title()} {params[0]}"
    return ""


def _expand_templates(text):
    result = []
    idx = 0
    while idx < len(text):
        if text.startswith("{{", idx):
            end, content = _extract_template(text, idx)
            if end is None:
                result.append(text[idx])
                idx += 1
                continue
            replacement = _render_template(content)
            if replacement:
                result.append(replacement)
            idx = end
            continue
        result.append(text[idx])
        idx += 1
    return "".join(result)


def _clean_wikitext(text):
    text = HTML_COMMENT_RE.sub("", text)
    text = _expand_templates(text)
    text = _strip_templates(text)
    text = EXTERNAL_LINK_RE.sub(r"\2", text)
    text = EXTERNAL_LINK_SIMPLE_RE.sub(r"\1", text)
    text = WIKILINK_PIPED_RE.sub(r"\2", text)
    text = WIKILINK_RE.sub(r"\1", text)
    text = text.replace("'''", "").replace("''", "")
    text = TAG_RE.sub("", text)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"\s+([.,;:!?])", r"\1", text)
    return text


def _heading_level(line):
    match = HEADING_RE.match(line)
    if not match:
        return None, None
    return len(match.group(1)), match.group(2).strip()


def extract_english_definitions(text):
    definitions = []
    in_english = False
    for line in text.splitlines():
        level, heading = _heading_level(line)
        if level == 2:
            if heading.lower() == "english":
                in_english = True
            else:
                if in_english:
                    break
                in_english = False
            continue
        if not in_english:
            continue
        match = DEF_LINE_RE.match(line)
        if not match:
            continue
        content = match.group(2).strip()
        if not content or content.startswith(("*", ":")):
            continue
        cleaned = _clean_wikitext(content)
        if cleaned and HAS_ALNUM_RE.search(cleaned) and cleaned not in definitions:
            definitions.append(cleaned)
    return definitions


def parse_definitions(dump_path, target_words):
    definitions = {}
    targets = set(target_words)
    seen = set()
    with bz2.open(dump_path, "rb") as handle:
        context = ET.iterparse(handle, events=("start", "end"))
        _, root = next(context)
        for event, elem in context:
            if event != "end" or not elem.tag.endswith("page"):
                continue
            title_elem = elem.find("./{*}title")
            if title_elem is None or not title_elem.text:
                elem.clear()
                root.clear()
                continue
            title = title_elem.text.strip()
            key = title.lower()
            if key not in targets:
                elem.clear()
                root.clear()
                continue
            seen.add(key)
            text_elem = elem.find(".//{*}text")
            definitions_for_page = extract_english_definitions(text_elem.text or "")
            if definitions_for_page:
                existing = definitions.get(key)
                if existing:
                    for definition in definitions_for_page:
                        if definition not in existing:
                            existing.append(definition)
                else:
                    definitions[key] = definitions_for_page
            elem.clear()
            root.clear()
    missing = targets - seen
    return definitions, missing


def write_output(output_path, words, definitions):
    lines = []
    for word in words:
        defs = definitions.get(word, [])
        fields = [word] + defs
        lines.append(" | ".join(fields))
    Path(output_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main():
    args = parse_args()
    dump_path = Path(args.dump)
    if not dump_path.is_file():
        raise SystemExit(f"Dump file not found: {dump_path}")

    wordfreq_path = Path(args.wordfreqs)
    if not wordfreq_path.is_file():
        raise SystemExit(f"wordfreqs file not found: {wordfreq_path}")

    words = load_wordfreq_words(wordfreq_path)
    if not words:
        raise SystemExit(f"No words found in {wordfreq_path}")
    definitions, remaining = parse_definitions(dump_path, set(words))
    write_output(args.output, words, definitions)
    found = len(definitions)
    print(f"Wrote {len(words)} words to {args.output}")
    if remaining:
        print(f"Missing pages for {len(remaining)} words")
    print(f"Found definitions for {found} words")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
