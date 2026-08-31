from __future__ import annotations

import logging
import sys
import time

from . import db, ingest_fx, ingest_orders

log = logging.getLogger("pipeline")

SQL_STEPS = [
    "02_orders_clean.sql",
    "03_order_lines_eur.sql",
    "04_customer_spend_eur.sql",
    "05_country_category_revenue.sql",
]

CHECKS = [
    dict(
        name="orders_raw is populated",
        sql="select count(*) from orders_raw",
        expect=lambda v: v > 0,
        why="An API returning 200 with an empty body would otherwise wipe the marts.",
    ),
    dict(
        name="fx_rates is populated",
        sql="select count(*) from fx_rates",
        expect=lambda v: v > 0,
        why="No rates means no conversion is possible.",
    ),
    dict(
        name="FX data is fresh",
        sql="select current_date - max(rate_date) from fx_rates",
        expect=lambda v: v is not None and v <= 5,
        why=(
            "Days since the newest published rate. The ECB skips weekends and "
            "holidays, so 3 is normal on a Monday morning and 5 covers a long "
            "weekend - but a feed that has silently stopped updating shows up "
            "here as a number that keeps growing."
        ),
    ),
    # --- the cleaning rules still match the data --------------------------
    dict(
        name="orders_clean is populated",
        sql="select count(*) from orders_clean",
        expect=lambda v: v > 0,
        why="A cleaning rule that stops matching would empty the table.",
    ),
    dict(
        name="no test orders leaked through",
        sql="select count(*) from orders_clean where status = 'test'",
        expect=lambda v: v == 0,
        why="Internal test traffic must never reach a revenue table.",
    ),
    dict(
        name="every timestamp parsed",
        sql="select count(*) from orders_clean where order_ts is null",
        expect=lambda v: v == 0,
        why=(
            "The CASE in 02 has no ELSE, so a NEW timestamp format would appear "
            "here as nulls instead of an error. This is what turns that quiet "
            "degradation into a loud failure."
        ),
    ),
    dict(
        name="every category resolved",
        sql="select count(*) from orders_clean where category is null",
        expect=lambda v: v == 0,
        why="A new SKU prefix would fall through the category CASE.",
    ),
    dict(
        name="every customer identified",
        sql="select count(*) from orders_clean where customer_id is null",
        expect=lambda v: v == 0,
        why="A changed email format would break the customer_id recovery.",
    ),
    dict(
        name="no negative quantities remain",
        sql="select count(*) from orders_clean where qty < 0",
        expect=lambda v: v == 0,
        why="The abs() repair should leave none.",
    ),
    dict(
        name="grain is unique",
        sql="""
            select count(*) from (
                select order_id, sku from orders_clean
                group by 1, 2 having count(*) > 1
            ) duplicates
        """,
        expect=lambda v: v == 0,
        why=(
            "(order_id, sku) is the grain. The primary key already enforces "
            "this, so a failure here means the key itself is gone."
        ),
    ),
    # --- the conversion layer ---------------------------------------------
    dict(
        name="every line converted to EUR",
        sql="select count(*) from order_lines_eur where fx_rate is null",
        expect=lambda v: v == 0,
        why=(
            "The as-of join is a LEFT join, so an unconvertible line survives "
            "with a null rate rather than disappearing. Counting them here is "
            "the whole reason it is a LEFT join."
        ),
    ),
    # --- the deliverables --------------------------------------------------
    dict(
        name="customer_spend_eur is populated",
        sql="select count(*) from customer_spend_eur",
        expect=lambda v: v > 0,
        why="Deliverable 4 must not be empty.",
    ),
    dict(
        name="country_category_revenue is populated",
        sql="select count(*) from country_category_revenue",
        expect=lambda v: v > 0,
        why=(
            "Deliverable 5. Strictly this table COULD be empty if no country "
            "cleared EUR 40,000 - but with this dataset three do, so an empty "
            "result means the conversion or the filter broke."
        ),
    ),
    dict(
        name="marts reconcile with the view",
        sql="""
            select round(abs(
                (select coalesce(sum(total_spend_eur), 0) from customer_spend_eur)
              - (select coalesce(sum(line_amount_eur), 0) from order_lines_eur
                 where status = 'completed')
            ), 2)
        """,
        expect=lambda v: v is not None and v <= 1,
        why=(
            "Cross-check: the customer mart must add up to the same total as "
            "the view it came from, allowing a EUR 1 tolerance for per-row "
            "rounding. Catches an aggregation or filter that silently drifts."
        ),
    ),
]

# Reported every run so the Actions log doubles as an audit trail. These are
# observations, not assertions - they are expected to move day to day.
SUMMARY = [
    ("orders_raw rows", "select count(*) from orders_raw"),
    ("orders_clean rows", "select count(*) from orders_clean"),
    ("fx_rates rows", "select count(*) from fx_rates"),
    ("newest FX rate date", "select max(rate_date) from fx_rates"),
    ("customers", "select count(*) from customer_spend_eur"),
    ("total spend EUR", "select round(sum(total_spend_eur), 2) from customer_spend_eur"),
    ("countries above threshold", "select count(*) from country_category_revenue"),
    (
        "lines still on provisional FX",
        "select count(*) from order_lines_eur where fx_rate_is_provisional",
    ),
]


def run_transforms() -> None:
    """Run every SQL step in one transaction.

    Postgres has transactional DDL, so DROP and CREATE TABLE roll back like any
    other statement. If step 05 fails, steps 02-04 are undone too and yesterday's
    tables are still standing, untouched.
    """
    with db.connect() as conn:
        for filename in SQL_STEPS:
            started = time.monotonic()
            db.run_sql_file(conn, filename)
            log.info("  %s (%.1fs)", filename, time.monotonic() - started)
        conn.commit()


def run_checks() -> list[str]:
    """Verify every assumption. Returns the names of the checks that failed."""
    failures: list[str] = []

    with db.connect() as conn:
        for check in CHECKS:
            value = db.scalar(conn, check["sql"])
            if check["expect"](value):
                log.info("  PASS  %-34s (%s)", check["name"], value)
            else:
                failures.append(check["name"])
                log.error("  FAIL  %-34s (%s)", check["name"], value)
                log.error("        %s", check["why"])

    return failures


def log_summary() -> None:
    with db.connect() as conn:
        for label, sql in SUMMARY:
            log.info("  %-30s %s", label, db.scalar(conn, sql))


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        stream=sys.stdout,
    )
    started = time.monotonic()

    log.info("=== 1/4 ingest orders ===")
    ingest_orders.main()

    log.info("=== 2/4 ingest FX rates ===")
    ingest_fx.main()

    log.info("=== 3/4 transforms ===")
    run_transforms()

    log.info("=== 4/4 data quality checks ===")
    failures = run_checks()

    log.info("=== summary ===")
    log_summary()

    elapsed = time.monotonic() - started

    if failures:
        # Non-zero exit is what makes the scheduler notice. Without it the run
        # is green, the tables are wrong, and nobody hears about it - the exact
        # silent failure this file exists to prevent.
        log.error("FAILED %s check(s) in %.1fs: %s", len(failures), elapsed, ", ".join(failures))
        sys.exit(1)

    log.info("pipeline completed successfully in %.1fs", elapsed)


if __name__ == "__main__":
    main()
