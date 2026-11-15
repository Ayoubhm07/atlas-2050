-- Chaque vente tombe dans l'emprise (bounding box) de son département, calculée sur les
-- contours IGN des communes de dim_commune. Attrape lon/lat inversés, coordonnées nulles
-- ou vente rattachée au mauvais département. Le test échoue sur chaque vente hors emprise.
with emprise as (
    select
        code_departement,
        min(st_xmin(st_geomfromwkb(geom_wkb))) as xmin,
        max(st_xmax(st_geomfromwkb(geom_wkb))) as xmax,
        min(st_ymin(st_geomfromwkb(geom_wkb))) as ymin,
        max(st_ymax(st_geomfromwkb(geom_wkb))) as ymax
    from {{ ref('dim_commune') }}
    group by code_departement
)

select v.id_mutation, v.code_departement, v.lon, v.lat
from {{ ref('fact_transactions') }} as v
left join emprise as e using (code_departement)
where e.code_departement is null
    or v.lon is null or v.lat is null
    or v.lon not between e.xmin and e.xmax
    or v.lat not between e.ymin and e.ymax
