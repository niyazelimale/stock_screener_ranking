import requests
from bs4 import BeautifulSoup
import json

def get_screener_data(url):
    session = requests.Session()
    
    # mimic a browser
    headers = {
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Referer': url
    }

    print(f"Fetching CSRF token from {url}...")
    try:
        response = session.get(url, headers=headers)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print(f"Error fetching page: {e}")
        return

    soup = BeautifulSoup(response.content, 'html.parser')
    csrf_token = soup.find('meta', {'name': 'csrf-token'})
    
    if not csrf_token:
        print("Error: Could not find CSRF token.")
        return

    token = csrf_token['content']
    print(f"CSRF Token found: {token}")

    # The scan_clause we found earlier
    scan_clause = "( {cash} (  weekly ema(  weekly rsi( 9 ) , 3 ) >  weekly wma(  weekly rsi( 9 ) , 21 ) and  1 week ago  ema(  weekly rsi( 9 ) , 3 )<=  1 week ago  wma(  weekly rsi( 9 ) , 21 ) and  market cap >=  5000 and  market cap <  100000 ) ) "
    
    payload = {
        'scan_clause': scan_clause
    }

    # Headers required for the POST request
    post_headers = headers.copy()
    post_headers.update({
        'X-Csrf-Token': token,
        'X-Requested-With': 'XMLHttpRequest', # Important!
        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'
    })

    print("Sending POST request to screener process...")
    try:
        post_response = session.post('https://chartink.com/screener/process', data=payload, headers=post_headers)
        post_response.raise_for_status()
        
        data = post_response.json()
        
        if 'data' in data:
            results = data['data']
            print(f"\nFound {len(results)} stocks:")
            print(f"{'Symbol':<15} {'Name':<30} {'Close':<10} {'Volume':<10}")
            print("-" * 65)
            for stock in results:
                 # Adjust keys based on actual response if needed, assumed standard keys
                item_symbol = stock.get('nsecode', stock.get('bsecode', 'N/A'))
                item_name = stock.get('name', 'N/A')
                item_close = stock.get('close', 'N/A')
                item_volume = stock.get('volume', 'N/A')
                
                print(f"{item_symbol:<15} {item_name:<30} {item_close:<10} {item_volume:<10}")
        else:
            print("No data found in response.")
            print("Response:", data)

    except requests.exceptions.RequestException as e:
        print(f"Error during POST request: {e}")
    except json.JSONDecodeError:
        print("Error decoding JSON response.")
        print("Response content:", post_response.text)

if __name__ == "__main__":
    screener_url = "https://chartink.com/screener/hm-weekly-crossover-midcap"
    get_screener_data(screener_url)
