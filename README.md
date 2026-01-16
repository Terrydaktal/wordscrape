# WordScrape

A multi-stage pipeline for extracting unique vocabulary from Telegram chat exports, filtering them against linguistic databases, and building a structured offline dictionary using Wiktionary.

## Project Structure

```text
/
├── telegram/                         # PHASE 1 & 2: Sourcing & Ranking
│   ├── tg_word_scrape.py             # Scrape words from HTML exports + OCR
│   ├── generate_freqs.py             # Filter outliers and rank by rarity/popularity
│   ├── score_discarded.py            # AI-based validation of discarded words
│   ├── wiktionary_define_and_collapse.py # Build offline dictionary from XML dump
│   ├── extract_words.py              # Utility: Strip definitions from output
│   ├── scrapedwords.txt              # Raw unique words from chat
│   ├── wordfreqs.txt                 # Filtered and ranked word list
│   ├── worddefs.txt                  # Final dictionary (word | definitions)
│   ├── worddefswordsonly.txt         # Plain list of words with definitions
│   ├── ocr_word_map.json             # Links words to their image sources
│   ├── discarded_words.txt           # Words removed during filtering
│   └── discarded_words_assessed.txt  # State file for AI scoring results
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
│   ├── fetch_google_freqs.py         # Script to download and extract Ngram data
│   └── google_master_freqs.txt       # Massive frequency list (7.9M words, generated)
└── requirements.txt                  # Dependencies (tqdm, wordfreq, etc.)
```

## Setup & Pipeline Execution

To process a new Telegram chat export, follow these steps in order.

### 1. Installation & Requirements
*   Python 3.12+
*   Tesseract OCR (for image scraping): `sudo apt install tesseract-ocr`
*   Setup environment and dependencies:
    ```bash
    python3 -m venv .venv
    source .venv/bin/activate
    pip install -r requirements.txt
    ```

### 2. Initial Setup (Reference Data)
Before processing a chat, you must generate the master reference lists. This typically only needs to be done once.

1.  **Google Ngram Data**: Download the large 7.9M word frequency list.
    ```bash
    python3 GoogleNgram/fetch_google_freqs.py
    ```
2.  **Wiktionary List**: Download the latest dump and extract English titles.
    ```bash
    python3 wiktionary/extract_english_titles.py  # This will download the ~1GB XML dump automatically
    python3 wiktionary/build_wiktionary_wordlist.py
    ```
3.  **WordNet List**:
    ```bash
    python3 wordnet/generate_wordnet_wordlist.py
    ```

### 3. Step-by-Step Pipeline

#### A. Word Extraction
Export your Telegram chat as **HTML** (ensure "Images" are checked). Then run:
```bash
python3 telegram/tg_word_scrape.py --chat-dir "/path/to/Telegram Desktop/ChatExport_2026-01-16/"
```
This produces `telegram/scrapedwords.txt` containing all raw alphanumeric tokens (inclusive of digits/apostrophes) and `telegram/ocr_word_map.json`.

#### B. Filtering & Ranking
Clean the raw scrape and rank words by rarity. By default, it uses Wiktionary, WordNet, Zipf, and Google Ngram data.
```bash
python3 telegram/generate_freqs.py
```

**Advanced Filtering:**
You can toggle specific linguistic sources using flags. If any flag is provided, only those selected are used:
- `--wiki`: Use Wiktionary word list.
- `--wordnet`: Use WordNet.
- `--zipf`: Use Zipf frequency (>0).
- `--ngram`: Use Google Ngram frequency (>0).
- `--pageviews`: Use Wiktionary pageviews (>0).
- `--strict`: Skip API-based pageview fetching for words not in the local Wiktionary list.

*Note: The script automatically caches Wikimedia API pageview counts. Words that fail all active filters are logged in `telegram/discarded_words.txt` in a formatted table showing their frequencies.*

#### C. Dictionary Building
Build the final offline dictionary (`telegram/worddefs.txt`) by extracting definitions from the Wiktionary XML dump.
```bash
python3 telegram/wiktionary_define_and_collapse.py
```
This script uses a cache (`wiktionary/wiktionary_definitions.txt`) to make subsequent runs nearly instantaneous.

#### D. AI Validation (Optional)
Use an LLM (Gemini/Gemma) to double-check words discarded during filtering (`discarded_words.txt`) to ensure no rare valid words were missed.
```bash
python3 telegram/score_discarded.py --auto-loop
```
This creates `telegram/discarded_words_assessed.txt`, scoring each word (0.0 to 1.0) and providing reasoning based on presence in major dictionaries (OED, Webster's, etc.). It is resumable and stateful.

---

## Reference Data Scripts
*   **`fetch_google_freqs.py`**: Downloads and extracts the 7.9M word Google Ngram frequency list.
*   **`get_pageviews.py`**: A background scraper to pre-populate the entire 937k Wiktionary vocabulary pageview database (optional).
*   **`extract_words.py`**: Utility to strip definitions from `worddefs.txt` to get a clean list of words that have valid definitions.
