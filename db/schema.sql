-- MarketLens structured database schema
-- Normalized so you can query e.g. "revenue trend for AAPL 2018-2024" in plain SQL,
-- and so it extends cleanly to S&P 500 later without a redesign.

CREATE TABLE IF NOT EXISTS companies (
    ticker      VARCHAR(10) PRIMARY KEY,
    cik         VARCHAR(10) UNIQUE NOT NULL,
    name        TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS filings (
    id                SERIAL PRIMARY KEY,
    accession_number  VARCHAR(25) UNIQUE NOT NULL,
    ticker            VARCHAR(10) REFERENCES companies(ticker),
    cik               VARCHAR(10),
    form              VARCHAR(10) NOT NULL DEFAULT '10-K',
    filing_date       DATE NOT NULL,
    report_date       DATE NOT NULL,
    primary_document  TEXT,
    url               TEXT,
    ingested_at       TIMESTAMP DEFAULT NOW()
);

-- One row per (company, metric, period) reported financial fact.
-- Sourced from EDGAR's companyfacts (XBRL) API — already normalized by SEC,
-- we just flatten it out of nested JSON into rows.
CREATE TABLE IF NOT EXISTS financial_facts (
    id                SERIAL PRIMARY KEY,
    ticker            VARCHAR(10) REFERENCES companies(ticker),
    taxonomy          TEXT NOT NULL,               -- e.g. 'us-gaap'
    tag               TEXT NOT NULL,               -- e.g. 'Revenues', 'EarningsPerShareBasic'
    unit              TEXT NOT NULL,               -- e.g. 'USD', 'USD-per-shares'        -- e.g. 'USD', 'USD-per-shares'
    value             NUMERIC NOT NULL,
    fiscal_year       INT NOT NULL,
    fiscal_period     VARCHAR(4) NOT NULL,         -- 'FY', 'Q1', 'Q2', 'Q3'
    period_start      DATE,
    period_end        DATE NOT NULL,
    accession_number  VARCHAR(25),                 -- which filing this came from
    form              TEXT,
    filed_date        DATE,
    frame             TEXT,
    CONSTRAINT uq_financial_facts
        UNIQUE (ticker, tag, unit, fiscal_year, fiscal_period, period_end)
);

CREATE INDEX IF NOT EXISTS idx_facts_ticker_tag ON financial_facts (ticker, tag);
CREATE INDEX IF NOT EXISTS idx_facts_fy ON financial_facts (fiscal_year);
CREATE INDEX IF NOT EXISTS idx_filings_ticker ON filings (ticker);
