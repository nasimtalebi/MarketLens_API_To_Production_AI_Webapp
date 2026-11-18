"""
src/ingest_edgar.py
برای هر شرکت این سه فایل را در data/raw/<TICKER>/ ذخیره می‌کند:
  - submissions.json         (فهرست همه‌ی گزارش‌های شرکت در SEC)
  - 10k_filings_index.json   (فقط گزارش‌های 10-K در بازه‌ی سال‌های شما + لینک دانلود)
  - companyfacts.json        (اعداد مالی XBRL: revenue، net income و ...)

اجرا (از ریشه‌ی پروژه):  python src/ingest_edgar.py
"""

import json
import sys
import time
from pathlib import Path

import requests

# تا بتوانیم config را import کنیم (ریشه‌ی پروژه را به مسیر Python اضافه می‌کنیم)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.companies import (  # noqa: E402
    COMPANIES,
    END_YEAR,
    RAW_DATA_DIR,
    START_YEAR,
    USER_AGENT,
)

PAUSE_SECONDS = 0.2  # SEC بیشتر از ۱۰ درخواست در ثانیه را نمی‌پذیرد

session = requests.Session()
session.headers.update({"User-Agent": USER_AGENT})


def get_json(url, retries=3):
    """یک URL را می‌گیرد و JSON برمی‌گرداند. اگر خطا شد چند بار دوباره تلاش می‌کند."""
    for attempt in range(1, retries + 1):
        try:
            time.sleep(PAUSE_SECONDS)
            response = session.get(url, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            print(f"  [warning] تلاش {attempt} از {retries} ناموفق بود: {error}")
            if attempt == retries:
                raise
            time.sleep(2 * attempt)


def save_json(path, data, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=indent)


def rows_from_block(block):
    """SEC داده‌ها را به شکل ستونی می‌دهد؛ این تابع آن را به لیست ردیف‌ها تبدیل می‌کند."""
    keys = list(block.keys())
    count = len(block.get("accessionNumber", []))
    return [{key: block[key][i] for key in keys} for i in range(count)]


def build_10k_index(ticker, cik, submissions):
    """از submissions، فقط 10-K های بازه‌ی سال‌ها را بیرون می‌کشد."""
    rows = rows_from_block(submissions["filings"]["recent"])

    # گزارش‌های قدیمی‌تر در فایل‌های جداگانه‌ای هستند
    for extra in submissions["filings"].get("files", []):
        extra_url = f"https://data.sec.gov/submissions/{extra['name']}"
        rows += rows_from_block(get_json(extra_url))

    cik_number = str(int(cik))  # بدون صفرهای اول، برای لینک Archives
    filings = []
    for row in rows:
        if row["form"] != "10-K":
            continue
        filing_year = int(row["filingDate"][:4])
        if not (START_YEAR <= filing_year <= END_YEAR):
            continue

        accession_no_dashes = row["accessionNumber"].replace("-", "")
        url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_number}/"
            f"{accession_no_dashes}/{row['primaryDocument']}"
        )
        filings.append(
            {
                "ticker": ticker,
                "cik": cik,
                "form": row["form"],
                "accession_number": row["accessionNumber"],
                "filing_date": row["filingDate"],
                "report_date": row.get("reportDate", ""),
                "primary_document": row["primaryDocument"],
                "url": url,
            }
        )

    filings.sort(key=lambda item: item["filing_date"])
    return filings


def main():
    for ticker, info in COMPANIES.items():
        cik = info["cik"]
        out_dir = RAW_DATA_DIR / ticker
        print(f"\n=== {ticker} ({info['name']}) ===")

        try:
            # 1) submissions.json
            print("  گرفتن submissions ...")
            submissions = get_json(f"https://data.sec.gov/submissions/CIK{cik}.json")
            save_json(out_dir / "submissions.json", submissions)

            # 2) 10k_filings_index.json
            filings = build_10k_index(ticker, cik, submissions)
            index = {
                "ticker": ticker,
                "company": info["name"],
                "cik": cik,
                "start_year": START_YEAR,
                "end_year": END_YEAR,
                "count": len(filings),
                "filings": filings,
            }
            save_json(out_dir / "10k_filings_index.json", index)
            print(f"  {len(filings)} گزارش 10-K پیدا شد.")

            # 3) companyfacts.json (فایل بزرگ است، پس بدون indent)
            print("  گرفتن companyfacts (ممکن است کمی طول بکشد) ...")
            facts = get_json(
                f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik}.json"
            )
            save_json(out_dir / "companyfacts.json", facts, indent=None)
            print("  تمام شد.")

        except Exception as error:  # اگر یک شرکت خراب شد، بقیه ادامه پیدا کنند
            print(f"  [error] برای {ticker} مشکلی پیش آمد: {error}")

    print("\nکار تمام شد.")


if __name__ == "__main__":
    main()
