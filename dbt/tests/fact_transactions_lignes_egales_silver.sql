-- Aucune vente perdue ni dupliquée entre le silver DVF et fact_transactions
-- (jointures d'appariement DPE / IRIS). Le test échoue si les deux comptes diffèrent.
with gold as (select count(*) as n from {{ ref('fact_transactions') }}),
silver as (select count(*) as n from {{ source('silver', 'dvf') }})
select gold.n as n_gold, silver.n as n_silver
from gold, silver
where gold.n <> silver.n
