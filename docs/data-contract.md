# Contrat de données ATLAS 2050

Basé sur les vérifications du 2026-11-15 ([sources.md](sources.md)). Périmètre : départements 33, 13, 59.

## 1. DVF géolocalisées — transactions
- **Ingestion :** fichiers nationaux `full-{annee}.csv.gz` filtrés sur `code_departement`
  (les fichiers par département sont archivés et annoncés supprimés fin novembre 2026 :
  on ne s'appuie pas dessus).
- **Clés :** `id_mutation`, `id_parcelle`, `code_commune`, `longitude`/`latitude`.
- **Règles qualité (silver) :**
  - garder `nature_mutation = 'Vente'` et `type_local IN ('Maison','Appartement')` ;
  - mutations multi-lots : une mutation avec plusieurs logements n'a qu'un prix global →
    on garde seulement les mutations à **un seul logement** (le prix/m² serait faux sinon) ;
  - ventes avec un local commercial/industriel : rejetées ; dépendances (cave, garage) :
    gardées, comptées dans `n_dependances` (leur valeur est incluse dans le prix) ;
  - rejeter `valeur_fonciere` nulle, < 1 000 € ou `surface_reelle_bati` < 9 m² ;
  - outliers : bornes [Q1 − 3·IQR ; Q3 + 3·IQR] calculées sur **log(prix/m²)**, par
    commune et type ; repli sur département et type si la commune a moins de 10 ventes.
    (En linéaire, la borne basse est négative pour 184 groupes sur 279 en Gironde et
    laisse passer des ventes symboliques à 8 €/m².) ;
  - rejeter les lignes sans coordonnées (comptées dans le rapport qualité).
- **Surface de terrain :** geo-DVF répète chaque nature de culture pour chaque local de la
  parcelle (produit cartésien). On somme les cultures d'un seul groupe de local, on prend
  le max par parcelle, puis on somme les parcelles. Pour un appartement, la valeur est
  laissée vide (c'est la parcelle de la copropriété).
- **Limite connue (à trancher au sprint 3) :** des ventes réelles très chères au m² bâti
  restent en silver quand le prix paie surtout le terrain ou l'emplacement (domaines
  viticoles avec plusieurs hectares, Lège-Cap-Ferret jusqu'à ~74 000 €/m²). Le modèle
  devra les marquer ou les exclure (ex. terrain > 1 ha), pas les effacer de silver.
- **Interdits (CGU DVF) :** ré-identification, indexation moteurs. Voir ADR 0005.

## 2. DPE ADEME `dpe03existant` — performance énergétique
- **Ingestion :** API data.ademe.fr, filtre `qs=code_departement_ban:{dep}`, pagination,
  ~400 k à 610 k lignes par département.
- **Clés :** `identifiant_ban` (= `id` BAN), `id_rnb`, coordonnées Lambert-93.
- **Règles :** classes `etiquette_dpe` dans A–G ; garder le DPE **le plus récent** par
  `identifiant_ban` ; DPE postérieurs à juillet 2021 uniquement (méthode actuelle).

## 3. BAN — référentiel d'adresses (pivot)
- **Ingestion :** `adresses-{dep}.csv.gz`.
- **Rôle :** pivot DVF ↔ DPE. `cad_parcelles` (séparateur `|`, à éclater) ↔ `id_parcelle` DVF ;
  `id` ↔ `identifiant_ban` DPE.
- **Géocodage en ligne :** `data.geopf.fr/geocodage/search` (l'ancienne api-adresse est en fin de vie).
- **Limite assumée :** une parcelle peut porter plusieurs adresses et plusieurs DPE
  (immeubles) → jointure DPE ↔ vente seulement si un DPE unique est rattaché, sinon
  DPE inconnu (une modalité à part, pas une valeur inventée).

## 4. Géorisques API v1 — risques
- **Endpoints :** `gaspar/catnat` (par commune), `gaspar/tri`, `gaspar/azi`, `rga?latlon=lon,lat`.
- **Quota :** 5 appels/s → client avec limiteur de débit + cache disque.
- **Stratégie :** risques par **commune** pour Cat-Nat/TRI/AZI ; RGA par **centroïde d'IRIS**
  (pas par bien, sinon ~1 M d'appels).
- **Piège :** AZI vide ≠ pas de risque d'inondation. Variable à trois états : oui / non / inconnu.
- **Constat réel (2026-11-15) :** AZI est vide pour les **534 communes de Gironde**
  (alors que l'endpoint répond pour la Dordogne et le Lot-et-Garonne) : la Gironde n'a
  pas d'atlas AZI dans GASPAR. Gironde : 7 972 arrêtés Cat-Nat, 65 communes en TRI.
  → Sprint 2 : ajouter les plans de prévention (PPRI, endpoint GASPAR des PPR) comme
  signal inondation principal ; AZI reste un complément là où il existe.

## 5. INSEE Filosofi IRIS 2021 + contours IRIS (IGN)
- **Ingestion :** `BASE_TD_FILO_IRIS_2021_DISP_CSV.zip` + contours IRIS (GPKG).
- **Piège :** IRIS seulement pour les communes ≥ 5 000 habitants → pour les autres,
  revenu au niveau commune. Utiliser une édition des contours **cohérente avec 2021**
  pour que les codes IRIS correspondent.
- **À confirmer :** licence IGN et nom du champ code IRIS dans le GPKG.

## 6. Projections climatiques DRIAS — BLOQUÉ pour l'automatisation
- Pas d'API : un compte DRIAS gratuit est nécessaire, téléchargement manuel des
  indicateurs (grille SAFRAN 8 km, CSV).
- **Plan :** une personne de l'équipe télécharge les indicateurs (jours > 35 °C,
  sécheresse des sols) pour RCP 4.5 et 8.5, horizons 2030 et 2050, et les dépose dans
  `data/raw/drias/`. Le DAG lit ce dossier, vérifie un manifeste (checksum, date) et
  échoue clairement si un fichier manque.

## Jointures (résumé)
```
DVF.id_parcelle ──► BAN.cad_parcelles ──► BAN.id ──► DPE.identifiant_ban
DVF (lon,lat)   ──► IRIS (ST_Contains) ──► Filosofi, maille DRIAS, RGA
DVF.code_commune ──► Géorisques Cat-Nat / TRI / AZI
```
