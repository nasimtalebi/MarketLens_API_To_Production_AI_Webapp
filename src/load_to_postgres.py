"""
src/load_to_postgres.py
1) schema.sql را اجرا می‌کند (جدول‌ها را می‌سازد اگر نباشند)
2) داده‌های data/raw/<TICKER>/ را داخل دیتابیس marketlens می‌ریزد

اتصال از DATABASE_URL داخل فایل .env خوانده می‌شود (password فقط آنجاست).
اجرا چند بار امن است: ردیف تکراری ساخته نمی‌شود.

اجرا (از ریشه‌ی پروژه):  python src/load_to_postgres.py
"""

import json
import os
import sys
from datetime import date
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from psycopg2.extras import execute_values

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.companies import (  # noqa: E402
    COMPANIES,
    END_YEAR,
    PROJECT_ROOT,
    RAW_DATA_DIR,
    START_YEAR,
)

SCHEMA_PATH = PROJECT_ROOT / "db" / "schema.sql"
BATCH_SIZE = 5000


def parse_date(text):
    """'2024-09-28' -> date. اگر خالی بود None برمی‌گرداند."""
    return date.fromisoformat(text) if text else None


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def run_schema(cur):
    print("اجرای db/schema.sql ...")
    cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))


def load_companies(cur):
    rows = [(ticker, info["name"], info["cik"]) for ticker, info in COMPANIES.items()]
    execute_values(
        cur,
        """
        INSERT INTO companies (ticker, name, cik) VALUES %s
        ON CONFLICT (ticker) DO UPDATE
            SET name = EXCLUDED.name, cik = EXCLUDED.cik
        """,
        rows,
    )
    print(f"companies: {len(rows)} ردیف")


def load_filings(cur, ticker):
    index_path = RAW_DATA_DIR / ticker / "10k_filings_index.json"
    if not index_path.exists():
        print(f"  [skip] {index_path.name} برای {ticker} پیدا نشد.")
        return 0

    rows = [
        (
            f["accession_number"],
            ticker,
            f["cik"],
            f["form"],
            parse_date(f["filing_date"]),
            parse_date(f["report_date"]),
            f["primary_document"],
            f["url"],
        )
        for f in read_json(index_path)["filings"]
    ]
    if rows:
        execute_values(
            cur,
            """
            INSERT INTO filings
                (accession_number, ticker, cik, form, filing_date,
                 report_date, primary_document, url)
            VALUES %s
            ON CONFLICT (accession_number) DO NOTHING
            """,
            rows,
        )
    return len(rows)


def is_annual(start, end):
    """مقدار balance-sheet (بدون start) قبول است؛ مقدار دوره‌ای باید حدود یک‌ساله باشد."""
    if start is None:
        return True
    return 350 <= (end - start).days <= 380


def collect_annual_facts(ticker, facts_json):
    """فقط مقدارهای سالانه‌ی 10-K در بازه‌ی START_YEAR تا END_YEAR."""
    rows = []
    for taxonomy, tags in facts_json.get("facts", {}).items():
        for tag, tag_data in tags.items():
            for unit, items in tag_data.get("units", {}).items():
                for item in items:
                    if item.get("form") != "10-K" or item.get("fp") != "FY":
                        continue
                    fiscal_year = item.get("fy")
                    if fiscal_year is None or not (START_YEAR <= fiscal_year <= END_YEAR):
                        continue

                    start = parse_date(item.get("start"))
                    end = parse_date(item["end"])
                    if not is_annual(start, end):
                        continue

                    rows.append(
                        (
                            ticker,
                            taxonomy,
                            tag,
                            unit,
                            item["val"],
                            start,
                            end,
                            fiscal_year,
                            item["fp"],
                            item["form"],
                            parse_date(item["filed"]),
                            item["accn"],
                            item.get("frame"),
                        )
                    )
    return rows


def load_facts(cur, ticker):
    facts_path = RAW_DATA_DIR / ticker / "companyfacts.json"
    if not facts_path.exists():
        print(f"  [skip] {facts_path.name} برای {ticker} پیدا نشد.")
        return 0

    rows = collect_annual_facts(ticker, read_json(facts_path))
    for i in range(0, len(rows), BATCH_SIZE):
        execute_values(
            cur,
            """
            INSERT INTO financial_facts
                (ticker, taxonomy, tag, unit, value, period_start, period_end,
                 fiscal_year, fiscal_period, form, filed_date,
                 accession_number, frame)
            VALUES %s
            ON CONFLICT ON CONSTRAINT uq_financial_facts DO NOTHING
            """,
            rows[i : i + BATCH_SIZE],
        )
    return len(rows)


def main():
    load_dotenv(PROJECT_ROOT / ".env")
    database_url = os.getenv("DATABASE_URL")
    if not database_url:
        sys.exit("DATABASE_URL داخل فایل .env پیدا نشد. فایل .env.example را به .env کپی کنید.")

    conn = psycopg2.connect(database_url)
    try:
        with conn:  # همه‌چیز در یک transaction؛ اگر خطا شد، هیچ‌چیز نیمه‌کاره نمی‌ماند
            with conn.cursor() as cur:
                run_schema(cur)
                load_companies(cur)

                for ticker in COMPANIES:
                    print(f"\n=== {ticker} ===")
                    n_filings = load_filings(cur, ticker)
                    n_facts = load_facts(cur, ticker)
                    print(f"  filings: {n_filings} | financial_facts: {n_facts}")

                cur.execute("SELECT COUNT(*) FROM companies")
                c = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM filings")
                f = cur.fetchone()[0]
                cur.execute("SELECT COUNT(*) FROM financial_facts")
                ff = cur.fetchone()[0]
        print(f"\nتعداد کل ردیف‌ها در دیتابیس: companies={c}, filings={f}, financial_facts={ff}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
