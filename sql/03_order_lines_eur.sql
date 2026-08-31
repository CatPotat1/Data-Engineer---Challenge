create or replace view order_lines_eur as

with latest_rate as (
    -- The newest rate date we currently hold. Anything after it is unsettled.
    select max(rate_date) as latest_rate_date from fx_rates
)

select
    o.order_id,
    o.sku,
    o.customer_id,
    o.customer_email,
    o.order_ts,
    o.status,
    o.channel,
    o.category,
    o.country,
    o.qty,
    o.unit_price,
    o.currency,
    o.line_amount,
    o.fx_reference_date,

    fx.rate                       as fx_rate,
    fx.rate_date                  as fx_rate_date,

    -- fx_rates stores how many units of the quote currency one EUR buys
    round(o.line_amount / fx.rate, 2) as line_amount_eur,

    -- True when the reference date runs past the last published rate, so the
    -- value above is a best-available estimate that a later run will revise.
    (o.fx_reference_date > lr.latest_rate_date) as fx_rate_is_provisional,

    -- True when the rate used is not from the reference date itself. Expected
    -- and correct for weekends and holidays - reported, not treated as a fault.
    (fx.rate_date <> o.fx_reference_date)       as fx_rate_carried_forward

from orders_clean o
cross join latest_rate lr

-- LEFT JOIN, not INNER: if a rate is somehow unavailable the line must survive
-- into the view with a NULL amount, so the daily checks can count it and
-- shout. An inner join would make the row vanish, which is the failure mode
-- this whole design is trying to avoid.
left join lateral (
    select f.rate, f.rate_date
    from fx_rates f
    where f.base_currency  = 'EUR'
      and f.quote_currency = o.currency
      and f.rate_date     <= o.fx_reference_date
    order by f.rate_date desc
    limit 1
) fx on true;