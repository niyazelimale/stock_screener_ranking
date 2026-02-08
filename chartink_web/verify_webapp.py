import requests
import time
import sys

BASE_URL = "http://127.0.0.1:8000/analyzer"
s = requests.Session()

def check_dashboard():
    print(f"Checking Dashboard at {BASE_URL}...")
    try:
        r = s.get(BASE_URL + "/")
        if r.status_code == 200:
            print("  [OK] Dashboard accessible.")
        else:
            print(f"  [FAIL] Dashboard returned {r.status_code}")
            sys.exit(1)
        # Get CSRF token from cookie
        csrf = s.cookies.get('csrftoken')
        return csrf
    except Exception as e:
        print(f"  [FAIL] Connection error: {e}")
        sys.exit(1)

def import_screeners(csrf):
    print("Importing screeners...")
    # This is a GET request in my implementation (redirects after)
    r = s.get(f"{BASE_URL}/config/import/")
    if r.status_code == 200:
        print("  [OK] Import triggered.")
    else:
        print(f"  [WARN] Import returned {r.status_code}")

def start_scan(csrf):
    print("Starting scan...")
    headers = {'X-CSRFToken': csrf, 'Referer': BASE_URL + '/'}
    r = s.post(f"{BASE_URL}/api/scan/start/", headers=headers)
    
    if r.status_code == 200:
        data = r.json()
        if data.get('status') == 'success':
            job_id = data.get('job_id')
            print(f"  [OK] Scan started. Job ID: {job_id}")
            return job_id
        else:
            print(f"  [FAIL] Scan start failed: {data}")
            sys.exit(1)
    else:
        print(f"  [FAIL] API returned {r.status_code}")
        print(r.text)
        sys.exit(1)

def poll_status(job_id):
    print("Polling status...")
    while True:
        r = s.get(f"{BASE_URL}/api/status/{job_id}/")
        if r.status_code == 200:
            data = r.json()
            status = data.get('status')
            progress = data.get('progress')
            print(f"  Status: {status} ({progress}%)")
            
            if status == 'COMPLETED':
                print("  [OK] Scan completed!")
                return
            elif status == 'FAILED':
                print("  [FAIL] Scan failed.")
                print(data.get('log'))
                sys.exit(1)
            
            time.sleep(2)
        else:
            print(f"  [FAIL] Status poll failed: {r.status_code}")
            sys.exit(1)

def check_results(job_id):
    print("Checking results page...")
    r = s.get(f"{BASE_URL}/results/{job_id}/")
    if r.status_code == 200:
        print("  [OK] Results page accessible.")
        if "High Conviction" in r.text or "active" in r.text:
            print("  [OK] Content validates.")
    else:
         print(f"  [FAIL] Results page returned {r.status_code}")

if __name__ == "__main__":
    csrf = check_dashboard()
    import_screeners(csrf)
    job_id = start_scan(csrf)
    poll_status(job_id)
    check_results(job_id)
