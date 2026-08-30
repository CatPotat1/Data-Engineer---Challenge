"""Ingest: 
pull orders_raw from the API into Postgres.
"""

from __future__ import annotations

import logging

import requests

from . import config, db

log = logging.getLogger(__name__)

# Column order
COLUMNS = [
    "order_id",
    "customer_id",
    "customer_email",
    "order_ts",
    "status",
    "channel",
    "sku",
    "product_name",
    "category",
    "qty",
    "unit_price",
    "currency",
    "country",
    "fx_reference_date",
]

PAGE_SIZE = 1000  # PostgREST limit


def fetch_orders() -> list[dict]:
    """Fetch every row from the source API, one page at a time.
    """
    session = requests.Session()
    rows: list[dict] = []
    offset = 0

    while True:
        response = session.get(
            config.ORDERS_API_URL,
            params={
                "apikey": config.ORDERS_API_KEY,
                "limit": PAGE_SIZE,
                "offset": offset,
                "order": "order_id",
            },
            timeout=60,
        )
        response.raise_for_status()
        page = response.json()

        if not page:
            break

        rows.extend(page)
        log.info("fetched %s rows (running total %s)", len(page), len(rows))

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return rows


def load_orders(rows: list[dict]) -> int:
    """Replace the contents of orders_raw with the freshly fetched rows.
    """
    with db.connect() as conn:
        db.run_sql_file(conn, "01_landing_tables.sql")

        with conn.cursor() as cur:
            cur.execute("truncate table orders_raw")

            copy_sql = f"copy orders_raw ({', '.join(COLUMNS)}) from stdin"
            with cur.copy(copy_sql) as copy:
                for row in rows:
                    # Everything lands as text. str() here rather than in SQL so
                    # that JSON nulls stay real NULLs instead of becoming "None".
                    copy.write_row(
                        [
                            None if row.get(col) is None else str(row.get(col))
                            for col in COLUMNS
                        ]
                    )

        conn.commit()
        loaded = db.scalar(conn, "select count(*) from orders_raw")

    return loaded


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    rows = fetch_orders()
    log.info("source returned %s rows", len(rows))

    loaded = load_orders(rows)
    log.info("orders_raw now holds %s rows", loaded)

    if loaded != len(rows):
        raise RuntimeError(f"load mismatch: fetched {len(rows)}, stored {loaded}")


if __name__ == "__main__":
    main()
