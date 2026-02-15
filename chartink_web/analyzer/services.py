import json
import time
import requests
import traceback
import csv
import os
from datetime import datetime, timedelta
from collections import Counter
from django.utils import timezone
from django.conf import settings
from .models import Screener, ScanJob, StockResult, ScanReport

# Selenium Imports
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.common.by import By

class ChartinkScanner:
    def __init__(self, job_id):
        self.job_id = job_id
        self.job = ScanJob.objects.get(id=job_id)
        self.session = requests.Session()
        self.requests_headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
             'X-Requested-With': 'XMLHttpRequest',
        }

    def log(self, message):
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.job.log += f"[{timestamp}] {message}\n"
        self.job.save(update_fields=['log'])
        print(f"[Job {self.job_id}] {message}")

    def update_progress(self, progress):
        self.job.progress = progress
        self.job.save(update_fields=['progress'])

    def run(self):
        try:
            self.job.status = 'RUNNING'
            self.job.started_at = timezone.now()
            self.job.save()
            self.log("Starting scan job...")

            screeners = Screener.objects.filter(is_active=True)
            total_screeners = screeners.count()
            
            if total_screeners == 0:
                self.log("No active screeners found.")
                self.job.status = 'COMPLETED'
                self.job.completed_at = timezone.now()
                self.job.progress = 100
                self.job.save()
                return

            self.log(f"Found {total_screeners} active screeners.")
            
            all_results = [] # To verify high conviction later
            
            for index, screener in enumerate(screeners):
                progress = int((index / total_screeners) * 90) # 0 to 90% for scanning
                self.update_progress(progress)
                
                self.log(f"Processing: {screener.name} ({screener.url})")
                try:
                    stocks = self.process_screener(screener.url)
                    self.log(f"  > Found {len(stocks)} stocks.")
                    
                    for stock in stocks:
                        symbol = stock.get('nsecode', stock.get('bsecode', 'Unknown'))
                        # Normalize symbol
                        if not symbol: continue
                        
                        result = StockResult(
                            job=self.job,
                            screener=screener,
                            symbol=symbol,
                            name=stock.get('name', ''),
                            nse_code=stock.get('nsecode'),
                            bse_code=stock.get('bsecode'),
                            close_price=stock.get('close'),
                            volume=stock.get('volume')
                        )
                        result.save()
                        all_results.append(symbol)
                        
                except Exception as e:
                    self.log(f"Error processing {screener.url}: {e}")
                    # Continue to next screener
            
            # High Conviction Logic
            self.log("Calculating high conviction stocks...")
            self.update_progress(95)
            
            from .models import GlobalSettings
            settings = GlobalSettings.get_setting()
            threshold = settings.min_ranking_threshold
            
            stock_counts = Counter(all_results)
            high_conviction_symbols = [symbol for symbol, count in stock_counts.items() if count >= threshold]
            
            if high_conviction_symbols:
                StockResult.objects.filter(job=self.job, symbol__in=high_conviction_symbols).update(is_high_conviction=True)
                self.log(f"Identified {len(high_conviction_symbols)} high conviction stocks (Threshold: {threshold}).")
            
            # Export to CSV
            self.log("Exporting results to CSV...")
            self.update_progress(98)
            csv_path = self.export_to_csv()
            if csv_path:
                self.log(f"CSV report saved: {csv_path}")
            
            self.job.status = 'COMPLETED'
            self.job.completed_at = timezone.now()
            self.job.progress = 100
            self.job.save()
            self.log("Scan completed successfully.")

        except Exception as e:
            self.log(f"Critical Job Error: {str(e)}")
            self.log(traceback.format_exc())
            self.job.status = 'FAILED'
            self.job.completed_at = timezone.now()
            self.job.save()

    def process_screener(self, url):
        """
        Process a single screener URL with a fresh driver instance.
        """
        driver = None
        try:
            # Setup Headless Chrome
            chrome_options = Options()
            chrome_options.add_argument("--headless=new") 
            chrome_options.add_argument("--no-sandbox")
            chrome_options.add_argument("--disable-dev-shm-usage")
            chrome_options.add_argument("--page-load-strategy=eager")
            chrome_options.add_argument("user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
            
            driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=chrome_options)
            driver.set_page_load_timeout(60)

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
                try:
                    scan_clause_raw = driver.execute_script("return window._captured_scan_clause;")
                    if scan_clause_raw:
                        break
                except:
                    pass
                time.sleep(0.5)

            # 4. Fallback: Find and Click 'Run Scan'
            if not scan_clause_raw:
                try:
                    run_button = None
                    xpath_locators = [
                        "//button[contains(text(), 'Run Scan')]",
                        "//input[@value='Run Scan']",
                        "//button[contains(@class, 'btn-primary')]",
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
                        
                        for i in range(10):
                            scan_clause_raw = driver.execute_script("return window._captured_scan_clause;")
                            if scan_clause_raw:
                                break
                            time.sleep(0.5)
                except:
                    pass

            # 5. Get CSRF Token
            try:
                csrf_element = driver.find_element(By.CSS_SELECTOR, "meta[name='csrf-token']")
                csrf_token = csrf_element.get_attribute("content")
            except:
                pass

            # 6. Process captured data
            stocks = []
            if scan_clause_raw and csrf_token:
                import urllib.parse
                decoded = urllib.parse.unquote(scan_clause_raw)
                
                final_scan_clause = None
                try:
                    json_data = json.loads(decoded)
                    if isinstance(json_data, dict) and 'scan_clause' in json_data:
                        final_scan_clause = json_data['scan_clause']
                except json.JSONDecodeError:
                    pass
                
                if not final_scan_clause:
                    if decoded.startswith('scan_clause='):
                        final_scan_clause = decoded.replace('scan_clause=', '', 1)
                    else:
                        final_scan_clause = decoded

                # Fetch data using requests
                selenium_cookies = driver.get_cookies()
                for cookie in selenium_cookies:
                    self.session.cookies.set(cookie['name'], cookie['value'])

                payload = {'scan_clause': final_scan_clause}
                post_headers = self.requests_headers.copy()
                post_headers.update({'X-Csrf-Token': csrf_token})

                process_url = 'https://chartink.com/screener/process'
                r = self.session.post(process_url, data=payload, headers=post_headers)
                r.raise_for_status()
                data = r.json()
                stocks = data.get('data', [])

            return stocks

        except Exception as e:
            raise e
        finally:
            if driver:
                driver.quit()
    
    def export_to_csv(self):
        """
        Export scan results to CSV file with timestamp.
        Returns the file path if successful, None otherwise.
        """
        try:
            # Create scan_reports directory if it doesn't exist
            base_dir = settings.BASE_DIR.parent if hasattr(settings.BASE_DIR, 'parent') else os.path.dirname(settings.BASE_DIR)
            reports_dir = os.path.join(base_dir, 'scan_reports')
            os.makedirs(reports_dir, exist_ok=True)
            
            # Generate filename with timestamp
            timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            filename = f'scan_report_{timestamp}.csv'
            filepath = os.path.join(reports_dir, filename)
            
            # Get all results with screener counts
            from django.db.models import Count
            results = StockResult.objects.filter(job=self.job).values(
                'symbol', 'name', 'nse_code', 'bse_code', 'close_price', 'volume', 'is_high_conviction'
            ).annotate(screener_count=Count('screener')).order_by('-screener_count', 'symbol')
            
            # Write to CSV
            with open(filepath, 'w', newline='', encoding='utf-8') as csvfile:
                fieldnames = ['Symbol', 'Name', 'NSE Code', 'BSE Code', 'Close Price', 'Volume', 'Screener Count', 'High Conviction']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
                
                writer.writeheader()
                for result in results:
                    writer.writerow({
                        'Symbol': result['symbol'],
                        'Name': result['name'],
                        'NSE Code': result['nse_code'] or '',
                        'BSE Code': result['bse_code'] or '',
                        'Close Price': result['close_price'] or '',
                        'Volume': result['volume'] or '',
                        'Screener Count': result['screener_count'],
                        'High Conviction': 'Yes' if result['is_high_conviction'] else 'No'
                    })
            
            # Save report metadata
            high_conviction_count = results.filter(is_high_conviction=True).values('symbol').distinct().count()
            ScanReport.objects.create(
                job=self.job,
                csv_file_path=filepath,
                total_stocks=results.values('symbol').distinct().count(),
                high_conviction_count=high_conviction_count
            )
            
            return filepath
            
        except Exception as e:
            self.log(f"Error exporting to CSV: {str(e)}")
            return None


def find_new_stocks(latest_job_id):
    """
    Compare the latest scan with a scan from approximately one week ago (6+ days).
    Returns a list of symbols that are new in the latest scan.
    """
    try:
        # Get the latest job's report
        latest_report = ScanReport.objects.filter(job_id=latest_job_id).first()
        if not latest_report:
            return None, "No report found for the latest scan."
        
        # Find a report from 6+ days ago
        week_ago = timezone.now() - timedelta(days=6)
        old_report = ScanReport.objects.filter(
            created_at__lte=week_ago
        ).order_by('-created_at').first()
        
        if not old_report:
            return None, "No scan data from 6+ days ago found."
        
        # Get symbols from latest scan
        latest_symbols = set(
            StockResult.objects.filter(job_id=latest_job_id).values_list('symbol', flat=True).distinct()
        )
        
        # Get symbols from week-old scan
        old_symbols = set(
            StockResult.objects.filter(job_id=old_report.job_id).values_list('symbol', flat=True).distinct()
        )
        
        # Find new symbols
        new_symbols = latest_symbols - old_symbols
        
        # Get full details for new symbols from latest scan
        from django.db.models import Count, Max
        new_stocks = StockResult.objects.filter(
            job_id=latest_job_id,
            symbol__in=new_symbols
        ).values('symbol', 'name', 'nse_code', 'bse_code').annotate(
            screener_count=Count('screener'),
            close_price=Max('close_price'),
            volume=Max('volume'),
            is_high_conviction=Max('is_high_conviction')
        ).order_by('-screener_count', 'symbol')
        
        return {
            'new_stocks': list(new_stocks),
            'latest_scan_date': latest_report.created_at,
            'comparison_scan_date': old_report.created_at,
            'new_count': len(new_symbols),
            'latest_total': len(latest_symbols),
            'old_total': len(old_symbols)
        }, None
        
    except Exception as e:
        return None, f"Error comparing scans: {str(e)}"
