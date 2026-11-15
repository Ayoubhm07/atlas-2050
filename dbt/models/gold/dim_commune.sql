-- Une commune par ligne : contour = union de ses IRIS (les IRIS pavent la commune),
-- nom IGN, nombre d'adresses BAN, point intérieur pour la recherche.
-- nom_recherche : nom en minuscules sans accents (« Étauliers » → « etauliers »), clé de
-- la recherche par préfixe de l'API ; la saisie y est normalisée de la même façon.
with iris as (
    select code_insee, nom_commune, st_geomfromwkb(geom_wkb) as geom
    from {{ source('referentiel', 'contours_iris') }}
),

communes as (
    select
        code_insee,
        min(nom_commune) as nom_commune,
        st_union_agg(geom) as geom
    from iris
    group by code_insee
),

ban as (
    select code_insee, count(*) as n_adresses
    from {{ source('silver', 'ban') }}
    group by code_insee
)

select
    c.code_insee,
    c.nom_commune,
    lower(strip_accents(c.nom_commune)) as nom_recherche,
    case when c.code_insee like '97%' then left(c.code_insee, 3)
         else left(c.code_insee, 2) end as code_departement,
    coalesce(b.n_adresses, 0) as n_adresses,
    st_x(st_pointonsurface(c.geom)) as lon,
    st_y(st_pointonsurface(c.geom)) as lat,
    st_aswkb(c.geom) as geom_wkb
from communes as c
left join ban as b using (code_insee)
