"""
src/download_10k_html.py
گزارش‌های 10-K را (به شکل HTML) دانلود می‌کند و در
data/raw/<TICKER>/10k/ ذخیره می‌کند.

اول باید ingest_edgar.py اجرا شده باشد (چون از 10k_filings_index.json استفاده می‌کند).

اجرا (از ریشه‌ی پروژه):  python src/download_10k_html.py
"""

import json
import sys
import time
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.companies import COMPANIES, RAW_DATA_DIR, USER_AGENT  # noqa: E402

PAUSE_SECONDS = 0.2

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def download_file(url, destination, retries=3):
    """یک فایل را دانلود و ذخیره می‌کند. اگر خطا شد چند بار دوباره تلاش می‌کند."""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(PAUSE_SECONDS)
            response = session.get(url, timeout=60)
            response.raise_for_status()
            destination.write_bytes(response.content)
            return True
        except requests.RequestException as error:
            print(f"    [warning] تلاش {attempt} از {retries} ناموفق بود: {error}")
            if attempt == retries:
                return False
            time.sleep(2 * attempt)


def main():
    for ticker, info in COMPANIES.items():
        print(f"\n=== {ticker} ({info['name']}) ===")

        index_path = RAW_DATA_DIR / ticker / "10k_filings_index.json"
        if not index_path.exists():
            print("  فایل 10k_filings_index.json پیدا نشد. اول ingest_edgar.py را اجرا کنید.")
            continue

        with open(index_path, encoding="utf-8") as f:
            index = json.load(f)

        out_dir = RAW_DATA_DIR / ticker / "10k"
        out_dir.mkdir(parents=True, exist_ok=True)

        for filing in index["filings"]:
            accession = filing["accession_number"].replace("-", "")
            file_name = f"{ticker}_10K_{filing['filing_date']}_{accession}.htm"
            destination = out_dir / file_name

            # اگر قبلاً دانلود شده، رد شو
            if destination.exists() and destination.stat().st_size > 0:
                print(f"  [skip] {file_name} قبلاً دانلود شده.")
                continue

            print(f"  دانلود {file_name} ...")
            if download_file(filing["url"], destination):
                print("    انجام شد.")
            else:
                print("    [error] دانلود نشد.")

    print("\nکار تمام شد.")


if __name__ == "__main__":
    main()
