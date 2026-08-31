set local timezone = 'UTC';   -- makes every timestamp cast deterministic

drop table if exists orders_clean;

create table orders_clean as

with trimmed as (
    select
        nullif(trim(order_id), '')              as order_id,
        nullif(trim(customer_id), '')           as customer_id,
        lower(nullif(trim(customer_email), '')) as customer_email,
        nullif(trim(order_ts), '')              as order_ts,
        lower(nullif(trim(status), ''))         as status,
        lower(nullif(trim(channel), ''))        as channel,
        nullif(trim(sku), '')                   as sku,
        nullif(trim(product_name), '')          as product_name,
        nullif(trim(category), '')              as category,
        nullif(trim(qty), '')                   as qty,
        nullif(trim(unit_price), '')            as unit_price,
        upper(nullif(trim(currency), ''))       as currency,
        upper(nullif(trim(country), ''))        as country,
        nullif(trim(fx_reference_date), '')     as fx_reference_date
    from orders_raw
),


business as (
    select * from trimmed
    where status is distinct from 'test'
      and customer_email not like '%@aqurate.ai'
),

compacted as (
    select *,
           upper(regexp_replace(sku, '[^A-Za-z0-9]', '', 'g')) as sku_compact
    from business
),


typed as (
    select
        order_id,
        'SKU-'
            || substring(sku_compact from 4 for 2)
            || '-'
            || replace(substring(sku_compact from 6 for 3), 'O', '0') as sku,
        coalesce(
            customer_id::int,
            substring(customer_email from 'customer(\d+)@')::int
        )                                          as customer_id,
        (customer_id is null)                      as customer_id_recovered,

        customer_email,
        case
            when order_ts ~ '^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}$'
                then order_ts::timestamp
            when order_ts ~ '^\d{2}/\d{2}/\d{4} \d{2}:\d{2}$'
                then to_timestamp(order_ts, 'DD/MM/YYYY HH24:MI')::timestamp
            when order_ts ~ '^\d{9,11}$'
                then to_timestamp(order_ts::bigint)::timestamp
        end                                        as order_ts,

        status,
        channel,
        product_name,
        category,
        abs(qty::int)                              as qty,
        (qty::int < 0)                             as qty_sign_corrected,

        case when unit_price::numeric in (0, 999999)
             then null else unit_price::numeric end as unit_price,
        (unit_price::numeric in (0, 999999))        as unit_price_missing,

        currency,
        country,
        fx_reference_date::date                     as fx_reference_date
    from compacted
),

categorised as (
    select
        t.*,
        coalesce(
            t.category,
            case substring(t.sku from 5 for 2)
                when 'BK' then 'Books'
                when 'EL' then 'Electronics'
                when 'HK' then 'Home & Kitchen'
                when 'FA' then 'Fashion'
                when 'BE' then 'Beauty'
                when 'SP' then 'Sports'
            end
        )                    as category_resolved,
        (t.category is null) as category_recovered
    from typed t
),

deduped as (
    select
        *,
        row_number() over (
            partition by order_id, sku
            order by fx_reference_date asc nulls last
        ) as _rn
    from categorised
)

select
    order_id,
    sku,
    customer_id,
    customer_email,
    order_ts,
    status,
    channel,
    product_name,
    category_resolved as category,
    qty,
    unit_price,
    round((qty * unit_price)::numeric, 2) as line_amount,
    currency,
    country,
    fx_reference_date,

    -- Provenance flags
    customer_id_recovered,
    category_recovered,
    qty_sign_corrected,
    unit_price_missing
from deduped
where _rn = 1;

alter table orders_clean add primary key (order_id, sku);

create index if not exists orders_clean_customer_idx on orders_clean (customer_id);
create index if not exists orders_clean_fx_date_idx  on orders_clean (fx_reference_date);
create index if not exists orders_clean_cat_ctry_idx on orders_clean (category, country);