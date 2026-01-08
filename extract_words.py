import os

def extract_words(input_file, output_file):
    if not os.path.exists(input_file):
        print(f"Error: {input_file} not found.")
        return

    print(f"Reading from {input_file} and writing to {output_file}...")
    
    count = 0
    with open(input_file, 'r', encoding='utf-8') as infile, \
         open(output_file, 'w', encoding='utf-8') as outfile:
        for line in infile:
            # Extract the word before the first ' | ' separator
            word = line.split(' | ', 1)[0].strip()
            if word:
                outfile.write(word + '\n')
                count += 1
                
    print(f"Successfully extracted {count} words.")

if __name__ == "__main__":
    extract_words('worddefs.txt', 'worddefswordsonly.txt')

