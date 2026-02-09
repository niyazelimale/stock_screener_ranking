# Host on GitHub: GitHub Pages + GitHub Actions (Option B)

This document describes a complete, repeatable recipe to run your stock-screener scanner on GitHub only: use GitHub Actions to run scans (either a simple requests-based scraper or a Selenium-based browser automation) and publish the generated results as a static website on GitHub Pages.

Purpose
- Allow you to host a read-only, public website on GitHub Pages showing scan results.
- Use GitHub Actions to run scanning jobs (scheduled or manual) that produce JSON/CSV/HTML result files.
- Keep everything free (for public repos) and reproducible so you (or an LLM) can create the automation automatically later.

High-level architecture
- Scanner script (Python) runs in a GitHub Actions runner, fetches screening results, writes `results.json` (and optionally `results.csv` and a small `index.html`).
- A publishing Action uploads the generated site to the `gh-pages` branch (or `docs/`), which GitHub Pages serves as a static site.
- Triggers: `workflow_dispatch` (manual) and `schedule` (cron) for periodic runs.

Two variants (choose one)
1. Requests-based scanner (recommended first try)
   - Uses `chartink_poc.py` style requests to call the Chartink `/screener/process` endpoint using a known `scan_clause` or pre-extracted payload.
   - Pros: simple, faster, no headless Chrome required.
   - Cons: requires you to have the scan_clause available. If some screeners dynamically generate scan_clause via JS, you may need Selenium.

2. Selenium-based scanner (fallback when requests approach can't capture the payload)
   - Runs headless Chrome + chromedriver in the Action runner to load the screener page, intercept the `scan_clause`, then POST to Chartink.
   - Pros: faithful to your current local behavior.
   - Cons: needs extra Action setup, slightly slower, more dependencies.

Files to create (manifest)
- .github/workflows/scan_and_publish.yml           # Actions workflow (single workflow with a boolean flag to choose selenium vs requests or two separate workflows)
- scripts/scan_requests.py                        # Lightweight scanner that uses requests (based on chartink_poc.py)
- scripts/scan_selenium.py                        # Selenium-based scanner (a self-contained script, not depending on Django ORM)
- requirements.txt                                # Python dependencies
- static/index.html                                # A minimal static viewer that loads results.json and renders
- static/assets/*                                  # optional CSS/JS

Optional: if you prefer to publish from `docs/` in `main` branch instead of `gh-pages`, tweak the workflow to copy to `docs/` and push.

Detailed instructions (step-by-step)

1) Prepare a scanner script (Requests variant -- recommended)
- Create `scripts/scan_requests.py` with this contract:
  - Inputs: `--config path/to/screener_config.json` (JSON with list of screener URLs or scan_clauses), optional `--output results.json`.
  - Behavior: for each screener in config, fetch page to get csrf-token (if needed) and call `https://chartink.com/screener/process` with payload `{'scan_clause': scan_clause}`, with headers: `X-Requested-With: XMLHttpRequest` and `X-Csrf-Token: <token>`.
  - Output: write a JSON file with shape:
    {
      "generated_at": "2026-02-08T...Z",
      "screeners": [
         {"name": "hm-weekly-crossover-midcap", "url": "https://chartink.com/..", "results": [ {"symbol":"...","name":"..","close":..}, ... ]},
         ...
      ]
    }
- You can adapt `chartink_poc.py` to this script. Ensure it exits non-zero on critical failures (so Actions can fail when appropriate) and returns 0 on success.

2) Prepare a Selenium script (if needed)
- Create `scripts/scan_selenium.py` that:
  - Takes same `--config` and `--output` CLI.
  - Uses selenium with headless Chrome. Avoid importing Django: make it self-contained.
  - For each screener URL: use CDP or the existing interception JS (from `services.py`) to extract `scan_clause` and CSRF token, then POST using requests.Session (transfer cookies).
  - Write the same `results.json` output.
- Note: GitHub Actions Ubuntu runners can support Chrome. See the sample Actions YAML later which installs Chrome & chromedriver.

3) requirements.txt
- Start with:
  requests
  beautifulsoup4
  selenium  # only if using selenium variant
  webdriver-manager  # optional for local runs; in Actions we install system chromedriver

4) Static site
- Create `static/index.html` (or a small single-page JS) that fetches `results.json` and renders a simple table with timestamps and top N results. Keep it minimal.
- The workflow will publish `static/` directory as the root of the Pages site.

5) GitHub Actions workflow
- Create `.github/workflows/scan_and_publish.yml`. This workflow will:
  - Trigger: `workflow_dispatch` and `schedule` (daily or as you choose).
  - Inputs: `use_selenium` (boolean), `config_path` (path to screener_config.json in repo), `publish_branch` (default `gh-pages`).
  - Steps:
    - checkout
    - set up Python
    - install apt packages (selenium variant only): `google-chrome-stable`, `chromedriver` (or install chromium-chromedriver)
    - pip install -r requirements.txt
    - run `scripts/scan_requests.py --config $CONFIG --output results.json` (or selenium script if requested)
    - copy `static/` into a `site/` folder and add results.json into `site/`
    - publish `site/` to `gh-pages` using the `peaceiris/actions-gh-pages@v4` action (it uses GITHUB_TOKEN so no extra secret needed)

- Example YAML (Requests variant) -- place this into `.github/workflows/scan_and_publish.yml`:

```yaml
name: Scan and Publish (Requests)

on:
  workflow_dispatch:
    inputs:
      use_selenium:
        description: 'Use selenium instead of requests'
        required: false
        default: 'false'
      config_path:
        description: 'Path to screener config JSON'
        required: false
        default: 'screener_config.json'
  schedule:
    - cron: '0 2 * * *' # daily at 02:00 UTC

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - name: Checkout repo
        uses: actions/checkout@v4
        with:
          persist-credentials: true

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.11'

      - name: Install dependencies
        run: |
          python -m pip install --upgrade pip
          pip install -r requirements.txt

      - name: Run scanner (requests)
        if: ${{ github.event.inputs.use_selenium != 'true' }}
        run: |
          python scripts/scan_requests.py --config "${{ github.event.inputs.config_path }}" --output results.json

      # Selenium variant will be covered in alternate workflow

      - name: Prepare site folder
        run: |
          mkdir -p site
          cp -r static/* site/ 2>/dev/null || true
          cp results.json site/

      - name: Publish to GitHub Pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_branch: 'gh-pages'
          publish_dir: './site'

```

- Example YAML (Selenium variant) notes
  - Add steps to install Chrome:
    - sudo apt-get update
    - sudo apt-get install -y unzip xvfb libxi6 libgconf-2-4 libappindicator3-1 libasound2
    - Download Chrome .deb from Google and `dpkg -i` it
    - Install chromedriver matching installed chrome via apt or by downloading an appropriate binary
  - Alternatively use `browserless` or prebuilt images, but the above works on `ubuntu-latest` with a few commands.

6) Publishing strategy (details)
- Use `peaceiris/actions-gh-pages` to publish the generated `site/` to `gh-pages` branch. This avoids manual git push overhead and works with the provided `GITHUB_TOKEN`.
- In repo Settings → Pages, set `gh-pages` branch as source and the root as `/`.

7) Local testing
- Run scanner locally:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/scan_requests.py --config screener_config.json --output results.json
# Open static/index.html (serve with: python -m http.server 8000 in the site folder)
```

- To simulate an Actions run locally, you can use `act` (https://github.com/nektos/act) but Chrome installation there can be tricky. Prefer testing the scanner script locally and then push to GitHub.

8) Verification steps (after workflow runs)
- Go to the Actions tab and open the run to see logs.
- Visit the Pages site: https://<your-username>.github.io/<repo>/ and check the data shown.
- Verify `results.json` contains expected data and timestamps.

9) Edge cases & troubleshooting
- CSRF tokens: some screeners might not include CSRF in static HTML. If so, requests approach may fail; use Selenium to capture the XHR payload instead.
- Rate limiting: Chartink may rate-limit requests; add delays between requests and avoid too-frequent schedules.
- Action runner limits: For public repos usage is generous; private repos may consume minutes from your account.
- Binary sizes: Chrome and chromedriver increase Action runtime; Selenium runs may time out if many screeners.

10) Security & legal
- Check Chartink's Terms of Service to ensure automated requests are allowed.
- Do not store secrets in the repo. If you need tokens later, use GitHub Secrets.

11) Quality gates & tests
- Add a small unit/integration test `tests/test_scanner_smoke.py` that runs `scripts/scan_requests.py` against a mock endpoint or a small local HTML file to validate output format.
- Have the workflow fail when `results.json` is missing or empty.

12) Optional niceties
- Add a small `README.md` in the `site/` with the `generated_at` timestamp.
- Create an Action output artifact with `results.json` for debugging runs (use `actions/upload-artifact`).

13) Ready-to-use LLM prompt (paste this next time to ask an LLM to create everything automatically)

```
I want you to implement "GitHub Pages + GitHub Actions" deployment for my repo `stock_screener_ranking`.
Requirements:
- Create a scanner script `scripts/scan_requests.py` (or `scripts/scan_selenium.py` if requests approach fails). Use `screener_config.json` in repo for list of screeners.
- Add `requirements.txt` with `requests`, `beautifulsoup4`, and `selenium` (selenium optional).
- Add `.github/workflows/scan_and_publish.yml` with triggers `workflow_dispatch` and daily schedule. Workflow must:
  - Checkout code, set up Python, install dependencies
  - Run the scanner script producing `results.json`
  - Copy `static/` into `site/` and include `results.json`
  - Publish `site/` to `gh-pages` branch using `peaceiris/actions-gh-pages@v4`
- Add `static/index.html` that fetches `/results.json` and renders the top results.
- Make sure the workflow supports an input `use_selenium` to switch to Selenium variant.
- Ensure the workflow fails on critical errors and uploads `results.json` as an artifact for debugging.

Provide:
- The scripts under `scripts/` (requests and selenium variants if applicable)
- The workflow YAML
- `requirements.txt`
- `static/index.html`
- A small `GITHUB_PAGES_SETUP.md` describing what you did

Assumptions you can make if unclear:
- Use `python3.11` in Actions
- GitHub Pages will be served from `gh-pages` branch
- No secrets needed for initial run

Finish by running a test Action locally? No, just create the files and provide guidance to run the workflow manually on GitHub.
```

14) Quick checklist to hand to an LLM or to do manually
- [ ] Create `scripts/scan_requests.py` (implement contract above)
- [ ] Create `requirements.txt`
- [ ] Create `static/index.html`
- [ ] Create `.github/workflows/scan_and_publish.yml` (requests-first, `use_selenium` option)
- [ ] Commit and push to `main`
- [ ] In Actions, run workflow manually or wait for first schedule
- [ ] Enable Pages from `gh-pages` branch
- [ ] Visit site and verify

15) Example minimal `scripts/scan_requests.py` logic (pseudo)
- Read `screener_config.json` which is: {"screeners": ["https://chartink.com/screener/..."]}
- For each URL:
  - GET page to read CSRF token from `<meta name="csrf-token">` (if present)
  - If scan_clause is pre-provided in config, use it; otherwise try to extract from page (some sites may inline it)
  - POST to `https://chartink.com/screener/process` with appropriate headers and payload
  - Collect `data` from JSON response
- Write aggregated JSON to `results.json`

Appendix: Helpful links
- peaceiris actions-gh-pages: https://github.com/peaceiris/actions-gh-pages
- GitHub Actions docs: https://docs.github.com/actions
- Selenium headless chrome in Actions (example): search for "Run Selenium Chrome in GitHub Actions"; typical steps are apt install chrome and chromedriver or download matching binaries.

---

If you want, I can now generate the exact files (workflow YAML + a starter `scripts/scan_requests.py`, `requirements.txt`, and `static/index.html`) and run a quick local smoke test of the scanner script. Which variant should I scaffold first: `requests` (recommended) or `selenium`?