"""
config/companies.py
تنظیمات پروژه MarketLens: شرکت‌ها، CIK، سال‌ها و هویت شما برای SEC.
"""

from pathlib import Path

# ریشه‌ی پروژه (پوشه‌ی MarketLens) و پوشه‌ی داده‌های خام
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DATA_DIR = PROJECT_ROOT / "data" / "raw"

# ---------------------------------------------------------------
# SEC از شما اسم و ایمیل می‌خواهد. فقط حروف انگلیسی (ASCII) بنویسید.
# حتماً YOUR_NAME را با اسم خودتان عوض کنید.
# ---------------------------------------------------------------



YOUR_NAME = "Nasim"
YOUR_EMAIL = "Nasim369nl@gmail.com"
USER_AGENT = f"MarketLens {YOUR_NAME} {YOUR_EMAIL}"

# بازه‌ی سال‌ها (بر اساس سال تاریخ ارائه‌ی گزارش به SEC یعنی filing date)
START_YEAR = 2018
END_YEAR = 2025

# شرکت‌ها: ticker -> اسم و CIK (CIK همیشه ۱۰ رقم با صفرهای اول)
COMPANIES = {
    "AAPL": {"name": "Apple", "cik": "0000320193"},
    "MSFT": {"name": "Microsoft", "cik": "0000789019"},
    "GOOGL": {"name": "Alphabet (Google)", "cik": "0001652044"},
    "AMZN": {"name": "Amazon", "cik": "0001018724"},
    "META": {"name": "Meta Platforms", "cik": "0001326801"},
    "NVDA": {"name": "Nvidia", "cik": "0001045450"},
    "TSLA": {"name": "Tesla", "cik": "0001318605"},
}
