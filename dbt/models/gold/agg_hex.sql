-- Agrégats H3 pré-calculés pour la carte (résolutions 7 et 9).
-- Une ligne par (hexagone, type de bien, année, étiquette DPE) ; « tous » = toutes
-- modalités (GROUPING SETS), car une médiane ne se recombine pas à partir de médianes.
-- ADR 0005, appliquée ici, dans les données elles-mêmes :
--   * suppression primaire : aucun agrégat de moins de 5 ventes ;
--   * suppression secondaire (différenciation) : si un total publié et l'un de ses
--     sous-groupes publiés (même hexagone, chaque modalité du total = « tous » ou celle
--     du sous-groupe) diffèrent de 1 à 4 ventes, la soustraction isolerait moins de
--     5 ventes : le sous-groupe est retiré (le total, vue principale de la carte, reste).
--     Une passe suffit : retirer des lignes ne crée aucune nouvelle paire ;
--   * prix médian arrondi à 10 €/m².
-- L'API filtre par emprise (centre de l'hexagone, index GIST) et par modalités : la
-- requête devient une lecture d'index au lieu d'un tri de milliers de ventes.
with ventes as (
    select h3_r7, h3_r9, type_local, cast(annee as varchar) as annee, dpe_etiquette, prix_m2
    from {{ ref('fact_transactions') }}
),

par_resolution as (
    select 7 as resolution, h3_r7 as h3, type_local, annee, dpe_etiquette, prix_m2 from ventes
    union all
    select 9 as resolution, h3_r9 as h3, type_local, annee, dpe_etiquette, prix_m2 from ventes
),

agg as (
    select
        resolution,
        h3,
        coalesce(type_local, 'tous') as type_local,
        coalesce(annee, 'tous') as annee,
        coalesce(dpe_etiquette, 'tous') as dpe_etiquette,
        count(*) as n_ventes,
        cast(round(median(prix_m2) / 10) * 10 as integer) as prix_m2_median
    from par_resolution
    group by grouping sets (
        (resolution, h3, type_local, annee, dpe_etiquette),
        (resolution, h3, type_local, annee),
        (resolution, h3, type_local, dpe_etiquette),
        (resolution, h3, annee, dpe_etiquette),
        (resolution, h3, type_local),
        (resolution, h3, annee),
        (resolution, h3, dpe_etiquette),
        (resolution, h3)
    )
    having count(*) >= 5  -- suppression primaire
),

publiable as (
    select
        resolution || '-' || h3 || '-' || type_local || '-' || annee || '-' || dpe_etiquette
            as id_agg,
        *
    from agg
),

differenciation as (
    -- suppression secondaire : mêmes règles d'inclusion que le test
    -- tests/agg_hex_pas_de_differenciation.sql
    select distinct s.id_agg
    from publiable as t
    inner join publiable as s
        on s.resolution = t.resolution
        and s.h3 = t.h3
        and s.id_agg <> t.id_agg
        and t.type_local in ('tous', s.type_local)
        and t.annee in ('tous', s.annee)
        and t.dpe_etiquette in ('tous', s.dpe_etiquette)
    where t.n_ventes - s.n_ventes between 1 and 4
)

select
    p.*,
    h3_cell_to_lng(h3_string_to_h3(p.h3)) as lon,
    h3_cell_to_lat(h3_string_to_h3(p.h3)) as lat
from publiable as p
where p.id_agg not in (select id_agg from differenciation)
