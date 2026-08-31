from __future__ import annotations

import datetime as dt
import logging

import requests

from . import config, db

log = logging.getLogger(__name__)

LOOKBACK_DAYS = 15

DEFAULT_START = dt.date.today() - dt.timedelta(days=90)

def determine_window() -> tuple[dt.date, dt.date]:
    """Work out which dates we need rates for, from the orders themselves.

    Deriving the window from the data rather than hardcoding it means the job
    keeps working if the source's date range moves.
    """
    with db.connect() as conn:
        db.run_sql_file(conn, "01_landing_tables.sql")
        conn.commit()
        earliest = db.scalar(
            conn,
            r"""
            select min(fx_reference_date)::date
            from orders_raw
            where fx_reference_date ~ '^\d{4}-\d{2}-\d{2}$'
            """,
        )

    start = (earliest - dt.timedelta(days=LOOKBACK_DAYS)) if earliest else DEFAULT_START

    end = dt.date.today()
    return start, end

def fetch_rates(start: dt.date, end: dt.date) -> list[tuple]:
    """Fetch EUR"""
    url = f"{config.FX_API_URL}/{start.isoformat()}..{end.isoformat()}"
    response = requests.get(
        url,
        params={
            "base": config.FX_BASE_CURRENCY,
            "symbols": ",".join(config.FX_QUOTE_CURRENCIES),
        },
        timeout=60,
    )
    response.raise_for_status()
    payload = response.json()

    rows = []
    for rate_date, quotes in sorted(payload.get("rates", {}).items()):
        for quote_currency, rate in quotes.items():
            rows.append((rate_date, config.FX_BASE_CURRENCY, quote_currency, rate))

    for rate_date in sorted(payload.get("rates", {})):
        rows.append((rate_date, config.FX_BASE_CURRENCY, config.FX_BASE_CURRENCY, 1))

    return rows

def load_rates(rows: list[tuple]) -> int:
    """Upsert rates. Re-running the job cannot create duplicates.

    ON CONFLICT DO UPDATE rather than DO NOTHING because the ECB can restate a
    rate; if it does, we want the corrected value, not the first one we saw.
    """
    with db.connect() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                """
                insert into fx_rates (rate_date, base_currency, quote_currency, rate)
                values (%s, %s, %s, %s)
                on conflict (rate_date, base_currency, quote_currency)
                do update set rate = excluded.rate, _ingested_at = now()
                """,
                rows,
            )
        conn.commit()
        total = db.scalar(conn, "select count(*) from fx_rates")
    return total

def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    start, end = determine_window()
    log.info("requesting FX rates %s -> %s", start, end)

    rows = fetch_rates(start, end)
    if not rows:
        raise RuntimeError(f"FX API returned no rates for {start}..{end}")

    total = load_rates(rows)
    log.info("upserted %s rate rows; fx_rates now holds %s", len(rows), total)

    with db.connect() as conn:
        latest = db.scalar(conn, "select max(rate_date) from fx_rates")
    log.info("latest published rate date: %s", latest)


if __name__ == "__main__":
    main()


