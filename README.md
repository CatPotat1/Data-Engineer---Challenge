# Orders pipeline

My submission

It pulls `orders_raw` from the challenge API into a Supabase Postgres database, cleans it, converts
every line to EUR using ECB reference rates, and builds two tables: total spend per customer, and
EUR revenue by country for Books and Electronics where the combined figure clears €40,000. A GitHub
Actions job runs the whole thing daily (3 times every day with the current settings).

I split the work so Python only moves data (HTTP, paging, credentials, scheduling) and SQL does all
the transforming. No business logic in Python, no network calls in SQL.

## What ends up in the database

| Object | What it is |
| --- | --- |
| `orders_raw` | Landing table. Every column is TEXT. 9,268 rows |
| `fx_rates` | Daily EUR reference rates from Frankfurter (ECB data) |
| `orders_clean` | Cleaned order lines. 8,937 rows |
| `order_lines_eur` | A view. Each line valued in EUR |
| `customer_spend_eur` | Deliverable 4. 1,873 customers |
| `country_category_revenue` | Deliverable 5. RO, HU, DE |

## Data issues I found

The source is 9,268 rows with only 6,031 distinct `order_id` values once the padding is trimmed, and
that turned out to be the most important thing in the dataset. They are **order lines**, not orders:
an order with three products arrives as three rows. If I had deduplicated on `order_id` I would have
deleted about a third of the revenue, and nothing would have thrown an error. The real key is
`(order_id, sku)`, and I set it as a primary key on `orders_clean` so it cannot quietly break later.

| Issue | Rows | What I did |
| --- | --- | --- |
| `order_id` not unique | 9,268 rows, 6,031 ids | Treated the grain as `(order_id, sku)` |
| Duplicate lines | 234 pairs | Kept one per pair. 191 were identical; 43 differed only in `fx_reference_date` |
| Internal test orders | 101 | Excluded. Flagged by both `status='test'` and an `@aqurate.ai` email |
| Three timestamp formats | all rows | ISO, `DD/MM/YYYY HH:MM`, and Unix epoch, routed by regex to three parsers |
| Broken SKUs | 3 variants | `SKU HK 003`, `SKUEL001`, `SKU-FA-O03`. 19 raw values, 16 real products |
| Missing `customer_id` | 103 | Recovered from the email address |
| Missing `category` | 79 | Derived from the SKU prefix |
| Negative quantities | 167 | Took `abs()` |
| Price sentinels (0 and 999999) | 37 | Set to NULL |
| Padded `order_id` | a few | Trimmed |

A few of these needed an actual decision rather than a fix.

**Negative quantities.** All 167 have `status='completed'`, so I couldn't tell at a glance whether
they were data entry errors or return lines reversing a sale. Those need opposite treatment. So I
checked whether any of them had a matching positive line on the same order and SKU — none did. That
ruled out reversals, and refunds are flagged by `status` anyway, so `abs()` was the safe call.

**The 43 conflicting duplicates.** Same customer, same product, same price, same timestamp — the only
difference was `fx_reference_date`. One sale recorded twice with different FX metadata. There's no
ingestion timestamp to say which row is newer, so I keep the earliest date. It's deterministic
across runs, and it leans toward dates that already have a published rate.

**Price sentinels.** I set them to NULL rather than filling them with the median price for that SKU.
Imputing would have put 37 invented numbers into a financial table where nobody downstream could
tell them apart from real ones. The marts count the lines they skipped so the gap is visible.

**Refunds.** I kept them in `orders_clean` with the status intact and excluded them in the marts
instead. Cleaning should fix what's wrong; whether a refund counts as spend is a business rule, and
it belongs somewhere obvious and easy to change.

**FX dates.** This one nearly caught me. Some `fx_reference_date` values fall on weekends and some
are in the future, and the ECB only publishes on business days. Joining `fx_reference_date =
rate_date` would have silently dropped or nulled roughly half the lines. So the view does an as-of
join instead — the most recent rate published on or before the reference date. Lines whose reference
date runs past the newest rate I hold are flagged `fx_rate_is_provisional`, because tomorrow's run
will revise them.

That flag is what makes the daily refresh visibly do something. The orders are static, but when the
31 August rate published, 2,193 lines stopped being provisional and every country total moved a few
cents.

## Monitoring

The question I tried to answer was: if this failed quietly, how would I ever know?

My rule was that a green run has to mean *correct*, not just *finished*. So there's no `try/except`
anywhere in the chain — if the API breaks or a transform fails, the exception propagates and the job
exits non-zero. And after every build, `run_pipeline.py` re-checks 14 things against the database:

- **Did the sources deliver?** Both tables non-empty, and FX no more than 5 days stale. A feed that
  silently stops updating shows up here as a number that keeps growing.
- **Do the cleaning rules still match?** No test rows leaked, every timestamp parsed, every category
  and customer resolved, no negative quantities left, grain still unique.
- **Did conversion work?** No lines with a null FX rate. This is also why the FX join is a LEFT join
  — an inner join would make an unconvertible line vanish instead of showing up in this count.
- **Do the numbers reconcile?** The customer table has to add up to the same total as the view it
  came from, within €1 for rounding.

Any failure logs what broke and why, then exits 1, which turns the Actions run red and triggers
GitHub's failure email.

The check I'm happiest with is the timestamp one. The `CASE` that parses timestamps has no `ELSE`,
so a brand new format wouldn't crash — it would produce NULLs and everything downstream would keep
working with less data. That check turns a silent problem into a loud one.

**What this doesn't cover.** A job that never *starts* sends no email, and I hit exactly that: my
first scheduled run never fired. GitHub Actions cron is best-effort — runs get delayed under load and
the first slot after a workflow is created is often skipped entirely. I added extra daily slots as a
hedge, which is cheap because the pipeline is idempotent, but that's a workaround rather than a fix.
In production I'd add a dead-man's-switch that alerts when `refreshed_at` goes stale, so silence
itself triggers a page. I'd also want alerts going somewhere better than one person's inbox.

## Known limitations

- The ingest is a full reload. Fine for 9,268 static rows, wrong for a real order feed — that would
  need an incremental upsert on a business key.
- The test-row filter mixes a NULL-safe comparison (`IS DISTINCT FROM`) with one that isn't
  (`NOT LIKE`). It works because `customer_email` has no NULLs, but that's an assumption, not a
  guarantee.
- The SKU repair uses hardcoded character positions, assuming every code is 8 characters once
  separators are stripped. True for all 19 values today; it would produce garbage rather than an
  error if that changed.
- Germany clears the €40,000 threshold by about €230. Since part of that revenue is FX-converted, a
  big enough move in the leu could drop it out of the table. That's the rule working correctly, but
  it means the table's membership isn't stable by construction.

## AI usage

I used Claude Code.

It help me write the first version of most of the pipeline. And it speed up my coding process after I identified the Data Issues and build the Arhitecture.

Working alone I'd have got somewhere similar but more slowly.