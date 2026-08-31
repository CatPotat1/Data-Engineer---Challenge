
drop table if exists country_category_revenue;

create table country_category_revenue as
with eligible as (
    select *
    from order_lines_eur
    where status = 'completed'
      and category in ('Books', 'Electronics')
      and line_amount_eur is not null
),

by_country as (
    select
        country,
        round(sum(line_amount_eur), 2)                                        as revenue_eur,
        round(sum(line_amount_eur) filter (where category = 'Books'), 2)       as books_revenue_eur,
        round(sum(line_amount_eur) filter (where category = 'Electronics'), 2) as electronics_revenue_eur,
        count(distinct order_id)                                               as orders,
        count(*)                                                               as order_lines,
        count(distinct customer_id)                                            as customers,
        count(*) filter (where fx_rate_is_provisional)                         as lines_on_provisional_fx
    from eligible
    group by country
    having sum(line_amount_eur) > 40000      -- strict >, per "exceeds"
)

select
    rank() over (order by revenue_eur desc) as revenue_rank,
    country,
    revenue_eur,
    books_revenue_eur,
    electronics_revenue_eur,
    orders,
    order_lines,
    customers,
    lines_on_provisional_fx,
    now() as refreshed_at
from by_country
order by revenue_eur desc;

alter table country_category_revenue add primary key (country);
