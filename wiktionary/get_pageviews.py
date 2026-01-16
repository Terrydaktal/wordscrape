#!/usr/bin/env python3
import datetime
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from threading import Lock

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None

PAGEVIEWS_API_BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/per-article"
PAGEVIEWS_USER_AGENT = "wiktionary-pageviews-scraper/1.0 (9lewis9@gmail.com)"
PAGEVIEWS_RETRY_CODES = {429, 500, 502, 503, 504}
START_DATE = "20150701"

def get_end_date():
    today = datetime.date.today()
    first_of_month = today.replace(day=1)
    return (first_of_month - datetime.timedelta(days=1)).strftime("%Y%m%d")

END_DATE = get_end_date()

def fetch_word_views(word, timeout=10, retries=3):
    title = quote(word.replace(" ", "_"), safe="")
    url = f"{PAGEVIEWS_API_BASE}/en.wiktionary/all-access/user/{title}/monthly/{START_DATE}/{END_DATE}"
    request = Request(url, headers={"User-Agent": PAGEVIEWS_USER_AGENT})
    
    for attempt in range(retries + 1):
        try:
            with urlopen(request, timeout=timeout) as response:
                data = json.load(response)
            items = data.get("items", [])
            return word, int(sum(item.get("views", 0) for item in items))
        except HTTPError as exc:
            if exc.code == 404:
                return word, 0
            if exc.code == 429: # Rate limit
                time.sleep(2 * (attempt + 1))
                continue
            if exc.code in PAGEVIEWS_RETRY_CODES and attempt < retries:
                time.sleep(1 * (attempt + 1))
                continue
            return word, 0
        except Exception:
            if attempt < retries:
                time.sleep(1)
                continue
            return word, 0
    return word, 0

def main():
    script_dir = Path(__file__).parent
    input_path = script_dir / "wiktionary_english_words.txt"
    output_path = script_dir / "wiktionary_pageviews.txt"
    
    if not input_path.exists():
        print(f"Error: {input_path} not found.")
        return

    # Load existing progress
    finished_words = {}
    if output_path.exists():
        print("Loading existing progress...")
        with output_path.open("r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().rsplit(" ", 1)
                if len(parts) == 2:
                    finished_words[parts[0]] = parts[1]
    
    # Load targets
    all_words = [line.strip() for line in input_path.open(encoding="utf-8") if line.strip()]
    remaining_words = [w for w in all_words if w not in finished_words]
    
    print(f"Total words: {len(all_words)}")
    print(f"Already finished: {len(finished_words)}")
    print(f"Remaining: {len(remaining_words)}")
    
    if not remaining_words:
        print("Everything is already up to date.")
        return

    file_lock = Lock()
    
    # Using 32 workers to be respectful but fast
    workers = 32
    
    with output_path.open("a", encoding="utf-8") as out_f:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            pbar = tqdm(total=len(remaining_words), unit="word") if tqdm else None
            
            # Submit in batches to avoid massive memory usage
            batch_size = 1000
            for i in range(0, len(remaining_words), batch_size):
                batch = remaining_words[i:i+batch_size]
                futures = {executor.submit(fetch_word_views, word): word for word in batch}
                
                for future in as_completed(futures):
                    word, count = future.result()
                    with file_lock:
                        out_f.write(f"{word} {count}\n")
                        out_f.flush()
                    if pbar:
                        pbar.update(1)

    if pbar:
        pbar.close()
    print(f"Finished! Data saved to {output_path}")

if __name__ == "__main__":
    main()
