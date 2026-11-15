-- Une vente DVF (silver) par ligne, enrichie :
--   * DPE via le pivot BAN : DVF.id_parcelle → BAN.parcelles (éclatées) → BAN.id
--     → DPE.identifiant_ban. Seuls comptent les DPE CONNUS À LA DATE DE LA VENTE
--     (date_dpe <= date_mutation) : un DPE établi après la vente n'existait pas pour
--     l'acheteur (fuite temporelle). À chaque adresse, on retient le plus récent de ces
--     DPE (à date égale, le plus grand numero_dpe). Le DPE n'est rattaché que si UNE
--     SEULE adresse a un DPE à cette date, sinon étiquette « inconnu » (modalité à
--     part, jamais une valeur inventée) ;
--   * IRIS par point dans polygone (extension spatial) ;
--   * index H3 résolutions 7 et 9 (extension communautaire h3).
-- Statut d'appariement (dpe_appariement), toutes les règles évaluées à la date de vente :
--   apparie        une seule adresse avec DPE, DPE du même type de bien que la vente
--   sans_adresse   parcelle absente de la BAN
--   sans_dpe       adresses trouvées mais aucun DPE établi au plus tard à la vente
--   plusieurs_dpe  plusieurs adresses avec DPE, ou appartement dans un immeuble à
--                  plusieurs DPE (le plus récent ne serait pas forcément le sien)
--   type_different DPE unique mais d'un autre type (ex. maison vendue, DPE appartement)
with ventes as (
    select * from {{ source('silver', 'dvf') }}
),

parcelle_adresse as (
    select distinct unnest(parcelles) as id_parcelle, id as id_ban
    from {{ source('silver', 'ban') }}
),

vente_adresse as (
    select v.id_mutation, v.date_mutation, pa.id_ban
    from ventes as v
    inner join parcelle_adresse as pa on pa.id_parcelle = v.id_parcelle
),

adresses as (
    select id_mutation, count(distinct id_ban) as n_adresses
    from vente_adresse
    group by id_mutation
),

dpe_a_la_vente as (
    -- par (vente, adresse) : le DPE le plus récent parmi ceux connus à la date de vente,
    -- et le nombre de DPE de l'adresse à cette date (fenêtre calculée avant QUALIFY)
    select
        va.id_mutation,
        d.identifiant_ban,
        d.numero_dpe,
        d.etiquette_dpe,
        d.etiquette_ges,
        d.date_dpe,
        d.type_batiment,
        count(*) over (partition by va.id_mutation, d.identifiant_ban) as n_dpe_adresse
    from vente_adresse as va
    inner join {{ source('silver', 'dpe') }} as d
        on d.identifiant_ban = va.id_ban
        and d.date_dpe <= va.date_mutation
    qualify row_number() over (
        partition by va.id_mutation, d.identifiant_ban
        order by d.date_dpe desc, d.numero_dpe desc
    ) = 1
),

candidats as (
    select
        id_mutation,
        count(*) as n_dpe,  -- adresses ayant au moins un DPE à la date de vente
        any_value(numero_dpe) as numero_dpe,
        any_value(etiquette_dpe) as etiquette_dpe,
        any_value(etiquette_ges) as etiquette_ges,
        any_value(date_dpe) as date_dpe,
        any_value(type_batiment) as type_batiment,
        any_value(n_dpe_adresse) as n_dpe_adresse
    from dpe_a_la_vente
    group by id_mutation
),

appariement as (
    select
        v.id_mutation,
        case
            when ad.id_mutation is null then 'sans_adresse'
            when c.id_mutation is null then 'sans_dpe'
            when c.n_dpe > 1 then 'plusieurs_dpe'
            when v.type_local = 'Appartement' and c.n_dpe_adresse > 1 then 'plusieurs_dpe'
            when c.type_batiment is distinct from lower(v.type_local) then 'type_different'
            else 'apparie'
        end as dpe_appariement,
        c.numero_dpe,
        c.etiquette_dpe,
        c.etiquette_ges,
        c.date_dpe
    from ventes as v
    left join adresses as ad using (id_mutation)
    left join candidats as c using (id_mutation)
),

iris as (
    select code_iris, st_geomfromwkb(geom_wkb) as geom from {{ ref('dim_iris') }}
),

ventes_iris as (
    -- un point sur une frontière commune à deux IRIS : on garde le plus petit code
    select v.id_mutation, i.code_iris
    from ventes as v
    inner join iris as i on st_contains(i.geom, st_point(v.lon, v.lat))
    qualify row_number() over (partition by v.id_mutation order by i.code_iris) = 1
)

select
    v.id_mutation,
    v.date_mutation,
    cast(v.annee as integer) as annee,
    case when v.code_commune like '97%' then left(v.code_commune, 3)
         else left(v.code_commune, 2) end as code_departement,
    v.code_commune,
    v.id_parcelle,
    v.type_local,
    v.surface_bati,
    v.pieces,
    v.surface_terrain,
    v.n_dependances,
    v.valeur_fonciere,
    v.prix_m2,
    v.lon,
    v.lat,
    vi.code_iris,
    h3_latlng_to_cell_string(v.lat, v.lon, 7) as h3_r7,
    h3_latlng_to_cell_string(v.lat, v.lon, 9) as h3_r9,
    a.dpe_appariement,
    case when a.dpe_appariement = 'apparie' then a.etiquette_dpe else 'inconnu' end
        as dpe_etiquette,
    case when a.dpe_appariement = 'apparie' then a.etiquette_ges end as dpe_etiquette_ges,
    case when a.dpe_appariement = 'apparie' then a.date_dpe end as dpe_date,
    case when a.dpe_appariement = 'apparie' then a.numero_dpe end as dpe_numero
from ventes as v
inner join appariement as a using (id_mutation)
left join ventes_iris as vi using (id_mutation)
