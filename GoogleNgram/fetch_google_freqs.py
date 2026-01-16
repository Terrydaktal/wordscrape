#!/usr/bin/env python3
import gzip
import shutil
import urllib.request
from pathlib import Path

def fetch_google_freqs():
    script_dir = Path(__file__).parent
    url = "https://raw.githubusercontent.com/hackerb9/gwordlist/master/1gramsbyfreq.txt.gz"
    gz_path = script_dir / "1gramsbyfreq.txt.gz"
    dest_path = script_dir / "google_master_freqs.txt"

    print(f"Downloading Google Ngram data from {url}...")
    with urllib.request.urlopen(url) as response, gz_path.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)

    print(f"Decompressing to {dest_path}...")
    with gzip.open(gz_path, "rb") as f_in, dest_path.open("wb") as f_out:
        shutil.copyfileobj(f_in, f_out)

    gz_path.unlink()
    print("Done!")

if __name__ == "__main__":
    fetch_google_freqs()
