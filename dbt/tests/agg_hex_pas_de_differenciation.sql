-- ADR 0005, différenciation : pour deux agrégats publiés du même hexagone dont l'un
-- (sous-groupe) est inclus dans l'autre (total : chaque modalité vaut « tous » ou la
-- même valeur), l'écart total − sous-groupe ne doit jamais être de 1 à 4 ventes, sinon
-- la soustraction isole moins de 5 ventes. Le test échoue sur chaque paire fautive.
select
    t.id_agg as id_total,
    s.id_agg as id_sous_groupe,
    t.n_ventes - s.n_ventes as ecart
from {{ ref('agg_hex') }} as t
inner join {{ ref('agg_hex') }} as s
    on s.resolution = t.resolution
    and s.h3 = t.h3
    and s.id_agg <> t.id_agg
    and t.type_local in ('tous', s.type_local)
    and t.annee in ('tous', s.annee)
    and t.dpe_etiquette in ('tous', s.dpe_etiquette)
where t.n_ventes - s.n_ventes between 1 and 4
