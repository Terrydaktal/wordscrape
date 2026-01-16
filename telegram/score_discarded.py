import argparse
import os
import sys
import time
import json
import shutil
import random
from pathlib import Path
from typing import List, Dict, Tuple

try:
    import google.generativeai as genai
except ImportError:
    print("Error: 'google-generativeai' library is required.")
    print("Please install it: pip install google-generativeai")
    sys.exit(1)

def parse_line(line: str) -> Tuple[str, str, str, str, str]:
    """
    Parses a fixed-width-ish line. 
    Expected input format from original file: WORD  G_MASTER  ZIPF
    Expected format in assessed file: WORD  G_MASTER  ZIPF  SCORE  REASONING
    Returns (word, g_master, zipf, score, reasoning)
    """
    parts = line.strip().split()
    if not parts:
        return "", "", "", "", ""
    
    word = parts[0]
    g_master = parts[1] if len(parts) > 1 else "0"
    zipf = parts[2] if len(parts) > 2 else "0.0"
    
    # Check if we already have score/reasoning
    # We assume if the file was created by us, it might have score/reasoning
    # But splitting by space is tricky if reasoning has spaces.
    # So we rely on the fixed structure we create.
    
    # Simpler approach: 
    # If it's the original file, it only has 3 columns.
    # If it's the assessed file, we treat everything after 3rd column as score/reasoning
    
    score = ""
    reasoning = ""
    
    if len(parts) > 3:
        score = parts[3]
    if len(parts) > 4:
        reasoning = " ".join(parts[4:])
        
    return word, g_master, zipf, score, reasoning

def initialize_assessed_file(input_path: Path, output_path: Path):
    """Creates the assessed file from input if it doesn't exist."""
    if output_path.exists():
        return

    print(f"Initializing {output_path} from {input_path}...")
    with input_path.open("r", encoding="utf-8") as fin:
        lines = fin.readlines()

    with output_path.open("w", encoding="utf-8") as fout:
        # header
        fout.write(f"{'WORD':<30} {'G_MASTER':<15} {'ZIPF':<10} {'SCORE':<5} {'REASONING'}\n")
        fout.write(f"{'-'*30} {'-'*15} {'-'*10} {'-'*5} {'-'*20}\n")
        
        start_idx = 0
        for i, line in enumerate(lines):
            if line.strip().startswith("WORD") or "----" in line:
                continue
            # Basic heuristic to skip headers in original file
            if "G_MASTER" in line: continue 
            
            parts = line.strip().split()
            if not parts: continue
            
            word = parts[0]
            g_master = parts[1] if len(parts) > 1 else "0"
            zipf = parts[2] if len(parts) > 2 else "0.0"
            
            # Write with placeholders for score/reasoning
            fout.write(f"{word:<30} {g_master:<15} {zipf:<10} {'-':<5} {'-'}\n")

def load_assessed_file(file_path: Path) -> List[dict]:
    """Loads the entire assessed file into memory."""
    data = []
    with file_path.open("r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("WORD") or "----" in line:
                continue
            parts = line.split()
            if not parts: continue
            
            word = parts[0]
            g_master = parts[1] if len(parts) > 1 else "0"
            zipf = parts[2] if len(parts) > 2 else "0.0"
            
            # Score is the 4th column. If it is '-', it's unscored.
            score_token = parts[3] if len(parts) > 3 else "-"
            
            # Reasoning is the rest
            reasoning = " ".join(parts[4:]) if len(parts) > 4 else "-"
            
            data.append({
                "word": word,
                "g_master": g_master,
                "zipf": zipf,
                "score": score_token,
                "reasoning": reasoning,
                "line_original": line # Keep raw line just in case, though we regenerate it
            })
    return data

def save_assessed_file(file_path: Path, data: List[dict]):
    """Writes the data back to the file."""
    with file_path.open("w", encoding="utf-8") as f:
        f.write(f"{'WORD':<30} {'G_MASTER':<15} {'ZIPF':<10} {'SCORE':<5} {'REASONING'}\n")
        f.write(f"{'-'*30} {'-'*15} {'-'*10} {'-'*5} {'-'*20}\n")
        for item in data:
            f.write(f"{item['word']:<30} {item['g_master']:<15} {item['zipf']:<10} {item['score']:<5} {item['reasoning']}\n")

def score_words_batch(model, words: List[str]) -> Dict[str, dict]:
    """Scores a batch of words using the LLM with retries."""
    # Updated Dictionary-Check Prompt
    prompt = (
        "TASK: DICTIONARY VALIDATION CHECK\n"
        "You are a strict database verification tool. Your ONLY job is to check if the following strings exist "
        "in at least one of these specific major dictionaries:\n"
        "1. Oxford English Dictionary (OED)\n"
        "2. Merriam-Webster Unabridged\n"
        "3. Collins English Dictionary\n"
        "4. Cambridge Dictionary\n"
        "5. Wordnik (only if backed by a valid source like American Heritage or Century)\n\n"
        "RULES:\n"
        "1. IF FOUND in any of the above -> SCORE 1.0\n"
        "2. IF NOT FOUND -> SCORE 0.0\n"
        "3. IGNORE wiktionary-only words, urban dictionary, or generic internet slang.\n"
        "4. IGNORE foreign words (German, French) unless they are established English loanwords in these dictionaries.\n"
        "5. DO NOT GUESS. If you are not 100% sure it is in one of these books, score 0.0.\n\n"
        "OUTPUT FORMAT (JSON ONLY):\n"
        '[{"word": "example", "score": 1.0, "reasoning": "Found in OED (archaic)."}, {"word": "fake", "score": 0.0, "reasoning": "Not in target dictionaries."}]\n\n'
        f"DATA TO CHECK: {json.dumps(words)}"
    )
    
    max_retries = 3
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt)
            text = response.text.strip()
            # Clean up if model adds markdown
            if text.startswith("```json"):
                text = text[7:]
            elif text.startswith("```"):
                text = text[3:]
            if text.endswith("```"):
                text = text[:-3]
            
            data = json.loads(text.strip())
            
            results = {}
            if isinstance(data, list):
                for item in data:
                    results[item["word"]] = {"score": float(item["score"]), "reasoning": item.get("reasoning", "")}
            elif isinstance(data, dict):
                 results[data["word"]] = {"score": float(data["score"]), "reasoning": data.get("reasoning", "")}
                 
            return results
        except Exception as e:
            if "429" in str(e):
                wait_time = (2 ** attempt) * 5
                print(f"Rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            print(f"Error processing batch: {e}")
            break
            
    return {} # Return empty on failure so we don't overwrite with bad data

def main():
    parser = argparse.ArgumentParser(description="Score discarded words using an LLM (Stateful Batching).")
    parser.add_argument("--input", default=str(Path(__file__).parent / "discarded_words.txt"), help="Original discarded_words.txt")
    parser.add_argument("--output", default=str(Path(__file__).parent / "discarded_words_assessed.txt"), help="Stateful output file")
    parser.add_argument("--api-key", default=os.environ.get("GOOGLE_API_KEY"), help="Google API Key")
    parser.add_argument("--model", default=None, help="Gemini/Gemma model to use")
    parser.add_argument("--batch-size", type=int, default=20, help="Number of words per run")
    parser.add_argument("--auto-loop", action="store_true", help="Keep running batches until done")
    
    args = parser.parse_args()
    
    if not args.api_key:
        print("Error: API Key is required. Set GOOGLE_API_KEY env var or use --api-key.")
        sys.exit(1)
        
    genai.configure(api_key=args.api_key)
    
    # Model selection logic
    model_name = args.model
    if not model_name:
        priority_models = ["models/gemini-2.0-flash", "models/gemma-3-27b-it"]
        for m in priority_models:
            try:
                test_model = genai.GenerativeModel(m)
                test_model.generate_content("ok")
                model_name = m
                break
            except Exception as e:
                print(f"Model {m} check failed: {e}")
                continue
        if not model_name:
            model_name = "models/gemma-3-27b-it"
    
    print(f"Using model: {model_name}")
    model = genai.GenerativeModel(model_name)
    
    input_path = Path(args.input)
    output_path = Path(args.output)
    
    # 1. Initialize output file if needed
    initialize_assessed_file(input_path, output_path)
    
    while True:
        # 2. Read current state
        data = load_assessed_file(output_path)
        
        # 3. Find unscored words
        unscored_indices = [i for i, item in enumerate(data) if item["score"] == "-"]
        
        if not unscored_indices:
            print("All words have been assessed!")
            break
            
        print(f"Total words: {len(data)}, Unassessed: {len(unscored_indices)}")
        
        # 4. Pick next batch (in order)
        batch_indices = unscored_indices[:args.batch_size]
        batch_words = [data[i]["word"] for i in batch_indices]
        
        print(f"Processing batch of {len(batch_words)} words: {batch_words[:5]}...")
        
        # 5. Score
        scores = score_words_batch(model, batch_words)
        
        # 6. Update data
        updated_count = 0
        for i in batch_indices:
            word = data[i]["word"]
            if word in scores:
                data[i]["score"] = str(scores[word]["score"])
                data[i]["reasoning"] = scores[word]["reasoning"]
                updated_count += 1
            else:
                print(f"Warning: No score returned for {word}")
        
        # 7. Save immediately
        save_assessed_file(output_path, data)
        print(f"Saved {updated_count} updates to {output_path}")
        
        if not args.auto_loop:
            break
            
        time.sleep(2) # Politeness delay

if __name__ == "__main__":
    main()
if __name__ == "__main__":
    main()
