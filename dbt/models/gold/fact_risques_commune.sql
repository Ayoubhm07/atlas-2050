-- Risques par commune interrogée dans Géorisques (une ligne par commune).
--   n_catnat / n_catnat_10ans : arrêtés Cat-Nat (tous / début d'événement dans les
--     10 ans avant date_reference, figée par run et stockée dans la table) ;
--   in_tri : commune dans un Territoire à Risque important d'Inondation ;
--   ppri   : au moins un PPRN inondation (PPRN-I) ou littoral (PPRN-L) ;
--   azi    : trois états. « oui » = commune dans un Atlas des Zones Inondables ;
--            « non » = interrogée, aucun AZI, ET le département a des AZI ailleurs
--            (l'atlas existe, la commune n'y figure pas) ; « inconnu » = jamais
--            interrogée, ou département sans aucun AZI (Gironde : aucun atlas dans
--            GASPAR, un résultat vide n'y veut pas dire « pas de risque »).
-- Une colonne est NULL quand l'endpoint n'a pas été interrogé pour la commune.
with couverture as (
    select * from {{ source('silver', 'couverture') }}
),

communes as (
    select distinct code_insee from couverture
),

etat as (
    select
        code_insee,
        max(case when endpoint = 'catnat' then n_enregistrements end) as cov_catnat,
        max(case when endpoint = 'tri' then n_enregistrements end) as cov_tri,
        max(case when endpoint = 'azi' then n_enregistrements end) as cov_azi,
        max(case when endpoint = 'pprn' then n_enregistrements end) as cov_pprn
    from couverture
    group by code_insee
),

catnat as (
    select
        code_insee,
        count(distinct code_national_catnat) as n_catnat,
        count(distinct code_national_catnat) filter (
            where date_debut_evt >= cast('{{ var("date_reference") }}' as date) - interval 10 year
        ) as n_catnat_10ans
    from {{ source('silver', 'catnat') }}
    group by code_insee
),

ppr as (
    select
        code_insee,
        count(*) as n_ppr,
        bool_or(risque_inondation) as ppri
    from {{ source('silver', 'pprn') }}
    group by code_insee
),

dep_azi as (
    select
        case when code_insee like '97%' then left(code_insee, 3)
             else left(code_insee, 2) end as code_departement,
        sum(n_enregistrements) > 0 as dep_a_des_azi
    from couverture
    where endpoint = 'azi'
    group by all
)

select
    c.code_insee,
    case when e.cov_catnat is not null then coalesce(k.n_catnat, 0) end as n_catnat,
    case when e.cov_catnat is not null then coalesce(k.n_catnat_10ans, 0) end
        as n_catnat_10ans,
    cast('{{ var("date_reference") }}' as date) as date_reference,
    case when e.cov_tri is not null then e.cov_tri > 0 end as in_tri,
    case when e.cov_pprn is not null then coalesce(p.ppri, false) end as ppri,
    case when e.cov_pprn is not null then coalesce(p.n_ppr, 0) end as n_ppr,
    case
        when e.cov_azi > 0 then 'oui'
        when e.cov_azi = 0 and d.dep_a_des_azi then 'non'
        else 'inconnu'
    end as azi
from communes as c
inner join etat as e using (code_insee)
left join catnat as k using (code_insee)
left join ppr as p using (code_insee)
left join dep_azi as d
    on d.code_departement = case when c.code_insee like '97%' then left(c.code_insee, 3)
                                 else left(c.code_insee, 2) end
