# WordScrape

A multi-stage pipeline for extracting unique vocabulary from Telegram chat exports, filtering them against linguistic databases, and building a structured offline dictionary using Wiktionary.

## Project Structure

```text
/
├── telegram/                         # PHASE 1 & 2: Sourcing & Ranking
│   ├── tg_word_scrape.py             # Scrape words from HTML exports + OCR
│   ├── generate_freqs.py             # Filter outliers and rank by rarity/popularity
│   ├── wiktionary_define_and_collapse.py # Build offline dictionary from XML dump
│   ├── extract_words.py              # Utility: Strip definitions from output
│   ├── scrapedwords.txt              # Raw unique words from chat
│   ├── wordfreqs.txt                 # Filtered and ranked word list
│   ├── worddefs.txt                  # Final dictionary (word | definitions)
│   ├── worddefswordsonly.txt         # Plain list of words with definitions
│   ├── ocr_word_map.json             # Links words to their image sources
│   └── discarded_words.txt           # Words removed during filtering
├── wiktionary/                       # MASTER REFERENCE DATA
│   ├── get_pageviews.py              # Script to build master pageview database
│   ├── wiktionary_pageviews.txt      # Cumulative pageview data (resumable)
│   ├── wiktionary_english_words.txt  # List of all valid English Wiktionary titles
│   ├── extract_english_titles.py     # Extract titles from raw XML dump
│   ├── build_wiktionary_wordlist.py  # Clean titles into a reference list
│   └── enwiktionary-...xml.bz2       # Raw Wiktionary XML dump (Source)
├── wordnet/                          # REFERENCE DATA
│   ├── generate_wordnet_wordlist.py  # Generate wordlist from NLTK WordNet
│   └── wordnet.txt                   # Reference list
├── GoogleNgram/                      # REFERENCE DATA
│   └── google_master_freqs.txt       # Massive frequency list (7.9M words)
└── requirements.txt                  # Dependencies (tqdm, wordfreq, etc.)
```

## Pipeline Execution

To process a new Telegram chat export, run the following scripts in order:

### 1. Extraction
Extracts all unique words from messages and uses OCR (Tesseract) on images.
```bash
./.venv/bin/python3 telegram/tg_word_scrape.py --chat-dir "/path/to/chat_export"
```

### 2. Sanitisation & Ranking
Filters out "garbage" (typos, non-words) and ranks the survivors by rarity. It uses Google Books Ngram data and Wiktionary Pageviews.
```bash
./.venv/bin/python3 telegram/generate_freqs.py
```
*Note: This script automatically updates the master `wiktionary/wiktionary_pageviews.txt` with any new words found.*

### 3. Definition Building
Processes the offline Wiktionary XML dump to find structured definitions for your ranked list.
```bash
./.venv/bin/python3 telegram/wiktionary_define_and_collapse.py
```

## Reference Data Scripts

These are used to build the foundational datasets and typically only need to be run once:

*   **Build Wiktionary List**: `extract_english_titles.py` -> `build_wiktionary_wordlist.py`
*   **Build WordNet List**: `generate_wordnet_wordlist.py`
*   **Master Pageview Scraper**: `get_pageviews.py` (Resumable background scraper for the entire 937k Wiktionary vocabulary).

## Requirements
*   Python 3.12+
*   Tesseract OCR (for image scraping)
*   Dependencies in `requirements.txt` (install via `pip install -r requirements.txt`)
