import json
import time
import csv
import os
from collections import Counter
from datetime import datetime
import requests
from bs4 import BeautifulSoup

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

class ChartinkAnalyzer:
    def __init__(self, config_file='screener_config.json'):
        self.config_file = config_file
        self.stock_counts = Counter()
        self.results = []
        self.session = requests.Session()
        self.requests_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
             'X-Requested-With': 'XMLHttpRequest',
        }
    def load_config(self):
        try:
            with open(self.config_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading config: {e}")
            return {'screeners': []}

    def close(self):
        pass # Driver is closed per-request now

    def process_screener(self, url):
        """
        Process a single screener URL with a fresh driver instance.
        """
        print(f"Processing: {url}")
        driver = None
        try:
            # Setup Headless Chrome for this specific request
            chrome_options = Options()
            chrome_options.add_argument("--headless=new") 
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--page-load-strategy=eager") # Don't wait for full load (images/css)
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.set_page_load_timeout(60) # Increased timeout

            print(f"  [.] Navigating to {url}...")
            
            # 1. Enable interception BEFORE navigation using CDP
            interceptor_script = """
            window._captured_scan_clause = null;
            const oldOpen = XMLHttpRequest.prototype.open;
            const oldSend = XMLHttpRequest.prototype.send;
            
            XMLHttpRequest.prototype.open = function(method, url) {
                this._method = method;
                this._url = url;
                return oldOpen.apply(this, arguments);
            };
            
            XMLHttpRequest.prototype.send = function(body) {
                if (this._method === 'POST' && this._url.includes('/screener/process')) {
                    window._captured_scan_clause = body;
                }
                return oldSend.apply(this, arguments);
            };
            """
            
            driver.execute_cdp_cmd('Page.addScriptToEvaluateOnNewDocument', {
                'source': interceptor_script
            })

            # 2. Navigate
            driver.get(url)

            # 3. Wait for capture (Auto-run)
            scan_clause_raw = None
            csrf_token = None
            
            for i in range(10): 
                scan_clause_raw = driver.execute_script("return window._captured_scan_clause;")
                if scan_clause_raw:
                    print("  [.] Captured scan_clause from auto-run.")
                    break
                time.sleep(0.5)

            # 4. Fallback: Find and Click 'Run Scan'
            if not scan_clause_raw:
                print("  [.] Auto-run not detected, attempting to click 'Run Scan'...")
                try:
                    run_button = None
                    xpath_locators = [
                        "//button[contains(text(), 'Run Scan')]",
                        "//button[contains(text(), 'Run Scan')]", 
                        "//input[@value='Run Scan']",
                        "//button[contains(@class, 'btn-primary')]",
                        "//button[contains(., 'Run Scan')]"
                    ]
                    
                    for xpath in xpath_locators:
                        try:
                            element = driver.find_element(By.XPATH, xpath)
                            if element.is_displayed():
                                run_button = element
                                break
                        except:
                            continue

                    if run_button:
                        driver.execute_script("arguments[0].scrollIntoView(true);", run_button)
                        time.sleep(0.5)
                        try:
                            run_button.click()
                        except:
                            driver.execute_script("arguments[0].click();", run_button)
                        print("  [.] Clicked 'Run Scan' button.")
                        
                        for i in range(10):
                            scan_clause_raw = driver.execute_script("return window._captured_scan_clause;")
                            if scan_clause_raw:
                                print("  [.] Captured scan_clause after click.")
                                break
                            time.sleep(0.5)
                    else:
                        print("  [!] Could not locate 'Run Scan' button.")
                        
                except Exception as e:
                    print(f"  [!] Error interacting with page: {e}")

            # 5. Get CSRF Token
            try:
                csrf_element = driver.find_element(By.CSS_SELECTOR, "meta[name='csrf-token']")
                csrf_token = csrf_element.get_attribute("content")
            except:
                print("  [!] CSRF token not found.")

            # 6. Process captured data
            stocks = []
            if scan_clause_raw and csrf_token:
                import urllib.parse
                decoded = urllib.parse.unquote(scan_clause_raw)
                
                final_scan_clause = None
                # Try parsing as JSON first
                try:
                    json_data = json.loads(decoded)
                    if isinstance(json_data, dict) and 'scan_clause' in json_data:
                        final_scan_clause = json_data['scan_clause']
                except json.JSONDecodeError:
                    pass
                
                # Fallback to string manipulation if not JSON or parsing failed
                if not final_scan_clause:
                    if decoded.startswith('scan_clause='):
                        final_scan_clause = decoded.replace('scan_clause=', '', 1)
                    else:
                        final_scan_clause = decoded

                # Fetch data using requests
                # We need cookies from driver
                selenium_cookies = driver.get_cookies()
                for cookie in selenium_cookies:
                    self.session.cookies.set(cookie['name'], cookie['value'])

                payload = {'scan_clause': final_scan_clause}
                post_headers = self.requests_headers.copy()
                post_headers.update({'X-Csrf-Token': csrf_token})

                try:
                    process_url = 'https://chartink.com/screener/process'
                    r = self.session.post(process_url, data=payload, headers=post_headers)
                    r.raise_for_status()
                    data = r.json()
                    stocks = data.get('data', [])
                    print(f"  [+] Found {len(stocks)} stocks.")
                    
                    if not stocks:
                        print(f"  [.] No stocks found in response.")

                except Exception as e:
                    print(f"  [!] API Request Error: {e}")
            else:
                 print("  [X] Failed to extract scan_clause or csrf_token.")

            return stocks

        except Exception as e:
            print(f"  [!] Error processing {url}: {e}")
            return []
        finally:
            if driver:
                driver.quit()

    def run(self):
        config = self.load_config()
        screeners = config.get('screeners', [])
        
        if not screeners:
            print("No screeners found in config.")
            return

        all_stocks_data = []

        print(f"Starting analysis of {len(screeners)} screeners...")
        print("-" * 50)

        for url in screeners:
            stocks = self.process_screener(url)
            
            for stock in stocks:
                symbol = stock.get('nsecode', stock.get('bsecode', 'Unknown'))
                name = stock.get('name', '')
                close = stock.get('close', 0)
                volume = stock.get('volume', 0)
                
                all_stocks_data.append({
                    'symbol': symbol,
                    'name': name,
                    'close': close,
                    'volume': volume,
                    'source_screener': url,
                    'scraped_at': datetime.now().isoformat()
                })
                
                self.stock_counts[symbol] += 1
            
            time.sleep(2) # Wait between screeners

        self.save_to_csv(all_stocks_data)
        self.print_top_conviction()
        # No self.close() needed as we close per request

    def save_to_csv(self, data):
        filename = 'screener_results.csv'
        if not data:
            print("\nNo data to save.")
            return
            
        keys = data[0].keys()
        try:
            with open(filename, 'w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=keys)
                writer.writeheader()
                writer.writerows(data)
            print(f"\n[+] Successfully saved {len(data)} rows to '{filename}'")
        except IOError as e:
             print(f"Error saving CSV: {e}")

    def print_top_conviction(self):
        print("\n" + "="*50)
        print("TOP 10 HIGH CONVICTION STOCKS")
        print("(Stocks appearing in multiple screeners)")
        print("="*50)
        
        top_10 = self.stock_counts.most_common(10)
        
        print(f"{'Count':<8} {'Symbol':<15}")
        print("-" * 25)
        
        for symbol, count in top_10:
            print(f"{str(count):<8} {symbol:<15}")

if __name__ == "__main__":
    app = ChartinkAnalyzer()
    try:
        app.run()
    except KeyboardInterrupt:
        print("\nInterrupted.")
        app.close()
    except Exception as e:
        print(f"\nCrash: {e}")
        app.close()
