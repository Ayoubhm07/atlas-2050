-- Pas de fuite temporelle : un DPE rattaché à une vente est établi au plus tard le jour
-- de la vente (le test échoue sur chaque vente dont le DPE est postérieur).
select id_mutation, date_mutation, dpe_date, dpe_numero
from {{ ref('fact_transactions') }}
where dpe_date > date_mutation
