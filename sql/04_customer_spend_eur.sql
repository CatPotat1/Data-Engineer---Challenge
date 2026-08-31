drop table if exists customer_spend_eur;

create table customer_spend_eur as
select
    customer_id,
    min(customer_email)                                     as customer_email,

    count(distinct order_id)                                as orders,
    count(*) filter (where line_amount_eur is not null)      as order_lines,
    coalesce(sum(qty) filter (where line_amount_eur is not null), 0) as units,

    -- The headline figure the brief asks for. COALESCE so that a customer
    -- whose every line was unpriced shows 0.00 rather than NULL.
    coalesce(round(sum(line_amount_eur), 2), 0)             as total_spend_eur,

    -- Same number split by original currency, so a reviewer can see how much
    -- of a customer's spend actually depended on a conversion.
    coalesce(round(sum(line_amount_eur) filter (where currency =  'EUR'), 2), 0) as spend_eur_native,
    coalesce(round(sum(line_amount_eur) filter (where currency <> 'EUR'), 2), 0) as spend_eur_converted,

    min(order_ts)                                           as first_order_ts,
    max(order_ts)                                           as last_order_ts,

    -- Transparency columns. These are what turn "trust me" into "check me".
    count(*) filter (where fx_rate_is_provisional)          as lines_on_provisional_fx,
    count(*) filter (where line_amount_eur is null)         as unpriced_lines,

    now()                                                   as refreshed_at

from order_lines_eur
where status = 'completed'
group by customer_id;

alter table customer_spend_eur add primary key (customer_id);

create index if not exists customer_spend_eur_total_idx
    on customer_spend_eur (total_spend_eur desc);
