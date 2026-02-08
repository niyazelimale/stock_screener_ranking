import requests
from bs4 import BeautifulSoup
import re

url = "https://chartink.com/screener/hm-weekly-crossover-midcap"
headers = {
    'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

print(f"Fetching {url}...")
try:
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    soup = BeautifulSoup(response.content, 'html.parser')
    
    print("Searching for 'scan_clause' in script tags...")
    found = False
    for i, script in enumerate(soup.find_all('script')):
        if script.string and 'scan_clause' in script.string:
            print(f"\n--- Found in Script Tag #{i} ---")
            # Print a snippet around the match
            match_index = script.string.find('scan_clause')
            snippet = script.string[max(0, match_index - 50):min(len(script.string), match_index + 200)]
            print(f"Snippet: ...{snippet}...")
            found = True
            
            # Try to regex it again to see why it failed
            match = re.search(r'scan_clause\s*=\s*"(.*?)(?<!\\)";', script.string, re.DOTALL)
            if match:
                print("Regex MATCHED!")
                print("Captured:", match.group(1)[:50] + "...")
            else:
                print("Regex FAILED.")

    if not found:
        print("scan_clause NOT found in any script tag.")

except Exception as e:
    print(f"Error: {e}")
