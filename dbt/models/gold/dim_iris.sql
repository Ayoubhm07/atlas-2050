-- Un IRIS par ligne : contour (WKB, EPSG:4326), point intérieur, revenus Filosofi 2021
-- (IRIS des communes ≥ 5 000 hab. seulement : NULL ailleurs) et exposition RGA.
with contours as (
    select * from {{ source('referentiel', 'contours_iris') }}
),

filosofi as (
    -- valeurs INSEE en texte à virgule décimale ; « ns »/« nd » (secret, non dispo) → NULL
    select
        IRIS as code_iris,
        try_cast(replace(DISP_MED21, ',', '.') as double) as revenu_median,
        try_cast(replace(DISP_TP6021, ',', '.') as double) as taux_pauvrete,
        try_cast(replace(DISP_GI21, ',', '.') as double) as gini,
        DISP_NOTE21 as filosofi_note
    from {{ source('referentiel', 'filosofi') }}
),

rga as (
    select code_iris, code_exposition, exposition
    from {{ source('silver', 'rga') }}
),

geo as (
    select
        *,
        st_pointonsurface(st_geomfromwkb(geom_wkb)) as point
    from contours
)

select
    g.code_iris,
    g.code_insee,
    g.nom_iris,
    g.type_iris,
    st_x(g.point) as lon,
    st_y(g.point) as lat,
    f.revenu_median,
    f.taux_pauvrete,
    f.gini,
    f.filosofi_note,
    r.code_exposition as rga_code_exposition,
    coalesce(r.exposition, 'inconnu') as rga_exposition,
    g.geom_wkb
from geo as g
left join filosofi as f using (code_iris)
left join rga as r using (code_iris)
