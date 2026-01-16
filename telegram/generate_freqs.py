#!/usr/bin/env python3
import argparse
import datetime
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

try:
    from wordfreq import zipf_frequency
except ImportError:
    zipf_frequency = None

PAGEVIEWS_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
PAGEVIEWS_USER_AGENT = "tgwordscrape/1.0"
PAGEVIEWS_RETRY_CODES = {429, 500, 502, 503, 504}
PAGEVIEWS_EARLIEST = "20150701"

def _default_pageviews_range(months, granularity):
    if months <= 0:
        start_date = PAGEVIEWS_EARLIEST
        if granularity == "monthly":
            today = datetime.date.today()
            first_of_month = today.replace(day=1)
            end_date = first_of_month - datetime.timedelta(days=1)
            end = end_date.strftime("%Y%m%d")
        else:
            end = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y%m%d")
        return start_date, end
    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    end_date = first_of_month - datetime.timedelta(days=1)
    year = end_date.year
    month = end_date.month
    for _ in range(months - 1):
        month -= 1
        if month == 0:
            month = 12
            year -= 1
    start_date = datetime.date(year, month, 1)
    return start_date.strftime("%Y%m%d"), end_date.strftime("%Y%m%d")

def _validate_yyyymmdd(value, label):
    if not value: return value
    if not re.fullmatch(r"\d{8}", value):
        raise ValueError(f"{label} must be in YYYYMMDD format.")
    return value

def _fetch_pageviews_word(word, *, project, access, agent, granularity, start, end, timeout, retries, backoff):
    title = quote(word.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS_API_BASE}/{project}/{access}/{agent}/{title}/{granularity}/{start}/{end}"
    request = Request(url, headers={"User-Agent": PAGEVIEWS_USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                import json
                data = json.load(response)
            items = data.get("items")
            return int(sum(item.get("views", 0) for item in items)) if items else 0
        except HTTPError as exc:
            if exc.code == 404: return 0
            if exc.code in PAGEVIEWS_RETRY_CODES and attempt < retries:
                time.sleep(backoff * (2**attempt))
                continue
            return 0
        except Exception:
            if attempt < retries:
                time.sleep(backoff * (2**attempt))
                continue
            return 0
    return 0

def fetch_pageviews(words, args, pageviews_file_path, valid_word_list=None):
    pageviews = {}
    
    if pageviews_file_path.is_file():
        print(f"Loading pageviews from {pageviews_file_path}...")
        with pageviews_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().rsplit(" ", 1)
                if len(parts) == 2:
                    pageviews[parts[0]] = int(parts[1])

    # Only fetch from API if word is in wiktionary_english_words.txt (valid_word_list)
    remaining = []
    skipped_count = 0
    for w in words:
        if w in pageviews:
            continue
        if valid_word_list is not None and w not in valid_word_list:
            pageviews[w] = 0
            skipped_count += 1
            continue
        remaining.append(w)

    if skipped_count:
        print(f"Skipping API fetch for {skipped_count} words not in Wiktionary list.")

    if remaining:
        print(f"Fetching {len(remaining)} missing words from API...")
        max_workers = max(1, min(int(args.pageviews_workers), len(remaining)))
        new_data = {}
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_word = {
                executor.submit(_fetch_pageviews_word, word, project=args.pageviews_project, access=args.pageviews_access,
                                agent=args.pageviews_agent, granularity=args.pageviews_granularity, start=args.pageviews_start,
                                end=args.pageviews_end, timeout=args.pageviews_timeout, retries=args.pageviews_retries,
                                backoff=args.pageviews_backoff): word for word in remaining
            }
            for future in as_completed(future_to_word):
                word = future_to_word[future]
                count = future.result()
                pageviews[word] = count
                new_data[word] = count
        
        if new_data:
            with pageviews_file_path.open("a", encoding="utf-8") as f:
                for word, count in new_data.items():
                    f.write(f"{word} {count}\n")
            print(f"Added {len(new_data)} new words to {pageviews_file_path}")
    
    return pageviews

def load_wordlist(path):
    if not path or not Path(path).is_file(): return set()
    return {line.strip().lower() for line in Path(path).open(encoding="utf-8") if line.strip() and not line.startswith("#")}

def load_master_frequency(path):
    freqs = {}
    if not path or not Path(path).is_file(): return freqs
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                word = " ".join(parts[:-1])
                count = parts[-1]
                try:
                    freqs[word.lower()] = int(count)
                except ValueError: continue
    return freqs

def load_pageviews_cache(pageviews_file_path):
    pageviews = {}
    if pageviews_file_path.is_file():
        with pageviews_file_path.open("r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().rsplit(" ", 1)
                if len(parts) == 2:
                    try:
                        pageviews[parts[0]] = int(parts[1])
                    except ValueError: continue
    return pageviews

def main():
    script_dir = Path(__file__).parent
    root_dir = script_dir.parent
    
    parser = argparse.ArgumentParser(description="Filter non-dictionary words and generate wordfreqs.txt")
    parser.add_argument("--input", default=str(script_dir / "scrapedwords.txt"))
    parser.add_argument("--output", default=str(script_dir / "wordfreqs.txt"))
    parser.add_argument("--discarded", default=str(script_dir / "discarded_words.txt"))
    parser.add_argument("--wiktionary-list", default=str(root_dir / "wiktionary" / "wiktionary_english_words.txt"))
    parser.add_argument("--wordnet-list", default=str(root_dir / "wordnet" / "wordnet.txt"))
    parser.add_argument("--master-list", default=str(root_dir / "GoogleNgram" / "google_master_freqs.txt"))
    parser.add_argument("--pageviews-file", default=str(root_dir / "wiktionary" / "wiktionary_pageviews.txt"))
    
    # Filtering Criteria Flags
    parser.add_argument("--wiki", action="store_true", help="Filter using Wiktionary English word list.")
    parser.add_argument("--wordnet", action="store_true", help="Filter using WordNet word list.")
    parser.add_argument("--zipf", action="store_true", help="Filter using Zipf frequency (>0).")
    parser.add_argument("--ngram", action="store_true", help="Filter using Google Ngram frequencies (>0).")
    parser.add_argument("--pageviews", action="store_true", help="Filter using Wiktionary pageview counts (>0).")
    
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--all", action="store_true", help="Keep all words from the scrape.")
    group.add_argument("--strict", action="store_true", help="Only keep words found in reference lists (no API-only words).")
    
    parser.add_argument("--pageviews-months", type=int, default=0)
    parser.add_argument("--pageviews-project", default="en.wiktionary")
    parser.add_argument("--pageviews-access", default="all-access")
    parser.add_argument("--pageviews-agent", default="user")
    parser.add_argument("--pageviews-granularity", default="monthly")
    parser.add_argument("--pageviews-workers", type=int, default=64)
    parser.add_argument("--pageviews-timeout", type=float, default=10.0)
    parser.add_argument("--pageviews-retries", type=int, default=2)
    parser.add_argument("--pageviews-backoff", type=float, default=0.5)
    
    args = parser.parse_args()
    
    start, end = _default_pageviews_range(args.pageviews_months, args.pageviews_granularity)
    args.pageviews_start = start
    args.pageviews_end = end

    if not Path(args.input).is_file():
        print(f"Input file not found: {args.input}")
        return 1

    scraped_words = load_wordlist(args.input)
    print(f"Loaded {len(scraped_words)} unique words from {args.input}")

    print(f"Loading Master Google Ngram frequencies (7.9M words)...")
    master_freqs = load_master_frequency(args.master_list)
    w_list = load_wordlist(args.wiktionary_list)
    n_list = load_wordlist(args.wordnet_list)
    pv_cache = load_pageviews_cache(Path(args.pageviews_file))

    final_words = set()
    discarded_words = set()

    # Determine which filters are active
    active_filters = {
        "wiki": args.wiki,
        "wordnet": args.wordnet,
        "zipf": args.zipf,
        "ngram": args.ngram,
        "pageviews": args.pageviews
    }
    # If no specific filters are requested, default to all of them
    if not any(active_filters.values()) and not args.all:
        for k in active_filters: active_filters[k] = True

    if args.all:
        print("Mode: --all. Keeping all words.")
        final_words = scraped_words
    else:
        filter_names = [k for k, v in active_filters.items() if v]
        print(f"Mode: Filtering. Active criteria: {', '.join(filter_names)}")
        if args.strict: print("Strict mode enabled: API checks disabled for unknown words.")

        for w in scraped_words:
            is_valid = False
            
            if active_filters["wiki"] and w in w_list:
                is_valid = True
            elif active_filters["wordnet"] and w in n_list:
                is_valid = True
            elif active_filters["zipf"] and zipf_frequency and zipf_frequency(w, "en") > 0:
                is_valid = True
            elif active_filters["ngram"] and master_freqs.get(w, 0) > 0:
                is_valid = True
            elif active_filters["pageviews"] and pv_cache.get(w, 0) > 0:
                is_valid = True
            
            # If not in local lists but we want to check pageviews API
            if not is_valid and active_filters["pageviews"] and not args.strict:
                # We'll include it for the API fetch later
                is_valid = True
            
            if is_valid:
                final_words.add(w)
            else:
                discarded_words.add(w)

    print(f"Final word count: {len(final_words)}")
    print(f"Discarded count: {len(discarded_words)}")

    if discarded_words:
        Path(args.discarded).write_text("\n".join(sorted(discarded_words)) + "\n", encoding="utf-8")
        print(f"Wrote discarded words to {args.discarded}")

    pageviews = fetch_pageviews(final_words, args, Path(args.pageviews_file), valid_word_list=w_list)
    
    # Post-fetch filtering: if it was only included for checking and it has 0 pageviews
    # AND it's not in any other active local lists, we discard it now.
    if not args.all:
        filtered_final = []
        for w in final_words:
            keep = False
            if active_filters["wiki"] and w in w_list: keep = True
            elif active_filters["wordnet"] and w in n_list: keep = True
            elif active_filters["zipf"] and (zipf_frequency and zipf_frequency(w, "en") > 0): keep = True
            elif active_filters["ngram"] and master_freqs.get(w, 0) > 0: keep = True
            elif active_filters["pageviews"] and pageviews.get(w, 0) > 0: keep = True
            
            if keep:
                filtered_final.append(w)
            else:
                discarded_words.add(w)
        
        if len(filtered_final) != len(final_words):
            print(f"Post-fetch filtering: {len(final_words) - len(filtered_final)} words removed for 0 pageviews.")
            # Update discarded words file if needed
            if discarded_words:
                Path(args.discarded).write_text("\n".join(sorted(discarded_words)) + "\n", encoding="utf-8")
        
        final_words_list = filtered_final
    else:
        final_words_list = list(final_words)

    sorted_words = sorted(
        final_words_list, 
        key=lambda w: (master_freqs.get(w, 0), pageviews.get(w, 0), w), 
        reverse=False
    )

    output_path = Path(args.output)
    if not sorted_words:
        print("No words left after filtering. Output not written.")
        return 0

    max_word_len = max([len(w) for w in sorted_words] + [4])
    header = f"{ 'WORD':<{max_word_len}}  {'IN_WIKI':>7}  {'G_MASTER':>15}  {'PAGEVIEWS':>10}  {'ZIPF':>10}"
    sep = f"{'-'*max_word_len}  {'-'*7}  {'-'*15}  {'-'*10}  {'-'*10}"
    lines = [header, sep]
    
    for w in sorted_words:
        in_wiki = "YES" if w in w_list else "NO"
        zipf = zipf_frequency(w, "en") if zipf_frequency else 0.0
        g_freq = master_freqs.get(w, 0)
        p_views = pageviews.get(w, 0)
        lines.append(f"{w:<{max_word_len}}  {in_wiki:>7}  {g_freq:>15d}  {p_views:>10d}  {zipf:>10.6f}")
    
    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {len(sorted_words)} words to {output_path}")

if __name__ == "__main__":
    main()