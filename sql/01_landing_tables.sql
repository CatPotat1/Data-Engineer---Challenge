create table if not exists orders_raw (
    order_id          text,
    customer_id       text,
    customer_email    text,
    order_ts          text,
    status            text,
    channel           text,
    sku               text,
    product_name      text,
    category          text,
    qty               text,
    unit_price        text,
    currency          text,
    country           text,
    fx_reference_date text,

    -- Audit column
    _ingested_at      timestamptz not null default now()
);

create table if not exists fx_rates (
    rate_date       date    not null,
    base_currency   text    not null,
    quote_currency  text    not null,
    rate            numeric not null,
    _ingested_at    timestamptz not null default now(),

    -- One rate per currency pair per day. 
    -- The primary key is what makes the daily FX load idempotent.
    primary key (rate_date, base_currency, quote_currency)
);

-- Speeds up the as-of rate lookup in the spend tables
create index if not exists fx_rates_lookup_idx
    on fx_rates (base_currency, quote_currency, rate_date desc);
