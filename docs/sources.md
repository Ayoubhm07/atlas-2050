# ATLAS 2050 - Sources de données ouvertes (vérification en ligne)

Date de vérification : 2026-11-15

Périmètre pilote : départements 33 (Gironde), 13 (Bouches-du-Rhône), 59 (Nord).
Méthode : requêtes HTTP réelles (curl) et lecture des métadonnées data.gouv.fr / OpenAPI. Tout ce qui n'a pas pu être confirmé est marqué "non confirmé".

## Tableau récapitulatif

| # | Source | Accès | Auth | Licence | Volume (33) | Dernière MAJ vue | Statut |
|---|--------|-------|------|---------|-------------|------------------|--------|
| 1 | DVF géolocalisées | CSV.gz | non | Licence Ouverte / Open Licence 2.0 | 2,2 à 3,3 Mo par an (dept 33) ; 116 Mo (France 2025) | données jusqu'au 2025-12-31 ; jeu data.gouv modifié le 2026-10-21 | OK, mais le chemin par département `latest` est ARCHIVÉ (voir section 1) |
| 2 | DPE ADEME `dpe03existant` | API Data Fair + CSV | non | Licence Ouverte / Open Licence 2.0 | 402 145 lignes (33), 491 709 (13), 612 770 (59) ; 16 003 705 France | données 2026-11-11 | OK |
| 3 | Géorisques API v1 | REST JSON | non (v1) ; Bearer pour v2 | etalab-2.0 (mention du site) | n/a (API) | non confirmé | OK, couverture AZI lacunaire |
| 4 | DRIAS (projections) | portail web | compte requis | Etalab (page conditions DRIAS) | n/a | newsletters jusqu'en 2025-12 | BLOQUÉ pour l'automatisation (section 4) |
| 5 | INSEE Filosofi IRIS 2021 + Contours-IRIS IGN | zip CSV + GPKG | non | non confirmé (INSEE) ; non confirmé (IGN) | 913 Ko (zip Filosofi) ; 88 Mo (IRIS France) | Filosofi paru 2024-07-31 ; IRIS édition 2026-01-01 (publiée 2026-07-03) | OK |
| 6 | BAN | CSV.gz par dept + API | non | Licence Ouverte / Open Licence 2.0 (fiche data.gouv) | 27,6 Mo (33), 18,9 Mo (13), 35,6 Mo (59) | fichiers du 2026-11-13 | OK ; ancienne API dépréciée |

Clés de jointure globales :
- DVF `id_parcelle` (14 car.) vers BAN `cad_parcelles` (liste séparée par `|`) : seul pont DVF vers adresse BAN.
- DPE `identifiant_ban` (ex. `33063_9315_00051`) vers BAN `id` (même format) : pont DPE vers BAN.
- Commune : `code_commune` (DVF) = `code_insee` (BAN) = `code_insee_ban` (DPE) = `code_insee` (Géorisques).
- IRIS : aucun code IRIS dans DVF/DPE/BAN, donc jointure spatiale (lon/lat dans polygone Contours-IRIS) puis clé `IRIS` (9 car.) avec Filosofi.

---

## 1. DVF géolocalisées (DGFiP, retraitement Etalab)

- Jeu data.gouv : https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres-geolocalisees/ (id `5cc1b94a634f4165e96436c1`).
- Jeu source DGFiP : https://www.data.gouv.fr/datasets/demandes-de-valeurs-foncieres/ (id `5c4ae55a634f4117716d5656`).
- URL département (testée, redirige 302 vers un bucket OVH, suivre avec `-L`) :
  `https://files.data.gouv.fr/geo-dvf/latest/csv/{année}/departements/{dep}.csv.gz`
  - Années présentes : 2021 à 2025. 2026 : 404.
  - Exemple testé : `curl -L -o 33.csv.gz https://files.data.gouv.fr/geo-dvf/latest/csv/2024/departements/33.csv.gz` donne 2 226 811 octets, 82 928 lignes (en-tête incluse).
  - Tailles de `33.csv.gz` : 2021 3,26 Mo ; 2022 3,22 Mo ; 2023 2,51 Mo ; 2024 2,23 Mo ; 2025 2,58 Mo. Fichier France entière par année : `.../csv/2025/full.csv.gz` = 98 Mo.
  - Last-Modified de ces fichiers : 2026-05-18 (livraison d'avril 2026).
- IMPORTANT, changement constaté : la ressource "Données au format CSV - livraison avril" pointant vers `files.data.gouv.fr/geo-dvf/latest/csv/` est étiquetée `[ARCHIVE] ... suppression au 31/11/2026` (sic, date invalide dans le libellé). Les fichiers par département risquent de disparaître. Un miroir `https://files.data.gouv.fr/geo-dvf/2025-12/csv/{année}/departements/{dep}.csv.gz` répond 200 (mêmes tailles) mais sa pérennité est non confirmée.
- Nouveau format officiel (livraison d'octobre 2026, jeu modifié le 2026-10-21) : un fichier national par année, sans découpage par département :
  - `https://static.data.gouv.fr/resources/demandes-de-valeurs-foncieres-geolocalisees/20261020-114721/full-2025.csv.gz` (116 267 867 o)
  - `.../20261020-114825/full-2026-s1.csv.gz` (51 711 646 o) ; 2022 : 141 Mo ; 2023 : 117 Mo ; 2024 : 107 Mo
  - fichier unique juillet 2021 à juin 2026 : `.../20261021-085741/dvf.csv.gz` (609 458 453 o).
  - Les URL `static.data.gouv.fr/resources/...` contiennent un horodatage et changent à chaque livraison : récupérer l'URL courante par l'API `https://www.data.gouv.fr/api/1/datasets/demandes-de-valeurs-foncieres-geolocalisees/` (champ `resources[].url`).
  - Test : les premiers Mo de `full-2025.csv.gz` ont le même en-tête (40 colonnes) que le fichier département. Filtrer ensuite `code_departement` dans {33, 13, 59}.
- Auth : aucune. Format : CSV UTF-8, séparateur virgule, WGS-84. Fréquence : semestrielle (avril et octobre), 5 ans glissants retraités à chaque livraison. Couverture temporelle déclarée : 2020-07-01 à 2025-12-31 (métadonnée) ; le jeu liste aussi 2026 S1.
- Colonnes clés (en-tête observé) : `id_mutation, date_mutation, nature_mutation, valeur_fonciere, adresse_numero, adresse_nom_voie, code_postal, code_commune, code_departement, id_parcelle, lot1_surface_carrez, nombre_lots, code_type_local, type_local, surface_reelle_bati, nombre_pieces_principales, nature_culture, surface_terrain, longitude, latitude`.
- Licence : Licence Ouverte / Open Licence version 2.0 (champ `license` = `lov2`, texte de la page).
- Conditions d'utilisation DVF (page du jeu source DGFiP, lue le 2026-11-15) :
  - Interdiction de ré-identification : l'usage "ne doit pas permettre la ré-identification des personnes concernées, de manière indirecte" (art. R112 A-3 du Livre des procédures fiscales).
  - Interdiction d'indexation : la réutilisation ne doit pas permettre l'indexation des données par des moteurs de recherche externes.
  - Les CGU complètes sont un PDF lié à la page (`conditions-generales-dutilisation-20201016.pdf`) ; je ne l'ai pas lu, son contenu exact est non confirmé.
  - Conséquence ATLAS : ne pas publier de tables transaction par transaction avec adresse exacte dans une page indexable ; agréger (IRIS, commune, grille) ou protéger l'accès.
- Jointures : `id_parcelle` vers BAN `cad_parcelles` ; `code_commune` vers INSEE/Géorisques ; lon/lat vers IRIS (spatial).
- Pièges :
  1. Une mutation = plusieurs lignes (une par parcelle/local) ; `valeur_fonciere` est répétée sur chaque ligne. Regrouper par `id_mutation` avant de calculer un prix/m2 et ne jamais sommer la valeur. `id_mutation` n'est pas stable d'une livraison à l'autre (doc du jeu).
  2. Filtrer `nature_mutation = Vente`, `type_local` dans {Maison, Appartement}, exclure les mutations multi-biens ou avec terrains mal ventilés ; `surface_reelle_bati` peut valoir 0 ou être vide ; les lots Carrez ne couvrent que les copropriétés. Alsace-Moselle et Mayotte absents (hors pilote). Le fichier 5 ans est entièrement retraité à chaque livraison : figer la version téléchargée (date + hash). Coordonnées au niveau parcelle, pas du bâtiment.

## 2. DPE ADEME - logements existants depuis juillet 2021 (`dpe03existant`)

- Page : https://data.ademe.fr/datasets/dpe03existant (titre : "DPE Logements existants (depuis juillet 2021)").
- API base : `https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant` (jeu virtuel filtrant `dpe_desactive=0` ; id interne `meg-83tjwtg8dyz4vv7h1dqe`).
- Endpoint lignes : `.../dpe03existant/lines`. Paramètres confirmés : `size`, `qs` (syntaxe Lucene), `select`, `after` (pagination par curseur, lien `next` fourni), `format=csv` (Content-Type text/csv testé).
- Exemple testé (dept 33) :
  `curl "https://data.ademe.fr/data-fair/api/v1/datasets/dpe03existant/lines?size=2&qs=code_departement_ban:33&select=numero_dpe,identifiant_ban,adresse_ban,code_insee_ban,coordonnee_cartographique_x_ban,coordonnee_cartographique_y_ban,etiquette_dpe,date_etablissement_dpe,surface_habitable_logement,type_batiment,score_ban,statut_geocodage,_geopoint"`
  Réponse : `total: 402145`, ex. `identifiant_ban: "33063_9315_00051"`, `etiquette_dpe: "C"`, `_geopoint: "44.8356,-0.5686"`.
- Filtre département : `qs=code_departement_ban:33` (champ confirmé dans le schéma). Totaux testés : 33 = 402 145 ; 13 = 491 709 ; 59 = 612 770. Existent aussi `code_postal_ban`, `code_insee_ban`, `code_region_ban`.
- Contient bien l'identifiant BAN et des coordonnées : `identifiant_ban`, `adresse_ban`, `score_ban`, `statut_geocodage`, `coordonnee_cartographique_x_ban` / `_y_ban` (Lambert-93 d'après l'ordre de grandeur des valeurs 441970 / 6391035 ; système non confirmé par la doc), `_geopoint` ("lat,lon"), et `id_rnb` (Référentiel National des Bâtiments). 230 colonnes au schéma.
- Auth : aucune pour la lecture (testé sans clé). Limite de débit : aucun en-tête de rate limit vu ; non confirmé.
- Licence : Licence Ouverte / Open Licence version 2.0 (métadonnée API). Format : JSON ou CSV (`format=csv`). Dernière mise à jour des données : 2026-11-11 (`dataUpdatedAt`) ; métadonnées 2026-10-29. Volume : 16 003 705 lignes (France).
- Jointure : `identifiant_ban` = `id` du CSV BAN ; `code_insee_ban` vers commune ; `id_rnb` vers RNB (hors périmètre).
- Pièges :
  1. La qualité du géocodage varie : l'exemple 33490 Saint-Maixant a `score_ban` 0,42 (adresse de type lieu-dit). Filtrer sur un score minimal (seuil à choisir et documenter) avant de joindre. Le DPE est par logement, pas par transaction : aucun lien direct avec une vente DVF, appariement par adresse/parcelle et date avec risque de faux appariements en copropriété.
  2. Volumétrie : 400 k à 600 k lignes par département. Plafond exact de `size` non confirmé ; utiliser `after`/`next` ou l'export CSV avec `qs` + `select`. L'endpoint `data-files` renvoie une liste vide (aucun fichier statique pré-généré confirmé).

## 3. Géorisques API v1

- Base : `https://georisques.gouv.fr/api/v1` (répond aussi sous `www.georisques.gouv.fr`). OpenAPI : https://www.georisques.gouv.fr/api/v3/api-docs/georisques-api-v1 ; documentation interactive : https://www.georisques.gouv.fr/doc-api.
- Auth : aucune pour v1 (tests sans jeton, HTTP 200). L'API v2 (`/api/v2/...`) exige un jeton `Authorization: Bearer` obtenu via https://www.georisques.gouv.fr/inscription (testé : 401 sans jeton). v2 n'expose ni `gaspar/catnat` ni `tri_zonage` (liste de chemins de l'OpenAPI v2).
- Limites de débit (texte de l'OpenAPI v1) : 1 appel/s pour `api/v1/resultats_rapport_risque` ; 1 appel/s pour `api/v1/rapport_pdf` ; 5 appels/s pour `api/v1/**`. v2 : 20 appels/s. Aucun en-tête de rate limit renvoyé lors des tests.
- Licence : "Sauf mention contraire, tous les contenus de ce site sont sous licence etalab-2.0" (page doc-api).
- Endpoints demandés (tous testés) :
  - Inondation, AZI : `GET /gaspar/azi?code_insee=` ou `?latlon=lon,lat&rayon=m` (+ `page`, `page_size`). Test 33063 (Bordeaux) : 0 résultat ; 33281 : 0 ; 59183 (Dunkerque) : 0 ; 13055 (Marseille) : 1 ("AZI13 - bassin de l'huveaune") ; 30189 (Nîmes) : 2.
  - Inondation, TRI : `GET /gaspar/tri?code_insee=33063` renvoie le TRI "BORDEAUX" (crue à débordement lent + submersion marine). Zonage TRI par point : `GET /tri_zonage?latlon=lon,lat&code=` (un test à Bordeaux a renvoyé 0 résultat : point non représentatif, comportement non confirmé).
  - Retrait-gonflement des argiles : `GET /rga?latlon=-0.5792,44.8378` renvoie `{"codeExposition":"2","exposition":"Exposition moyenne"}`. Seul paramètre : `latlon` (lon,lat). `rga?code_insee=...` renvoie 400 ("Des paramètres de recherches sont manquants").
  - Cat-nat par commune : `GET /gaspar/catnat?code_insee=33063&page=1&page_size=2` renvoie `results: 51`, `total_pages: 26` (Bordeaux), champs `code_national_catnat, date_debut_evt, date_fin_evt, date_publication_arrete, libelle_risque_jo, code_insee, libelle_commune` (dates au format `dd/mm/yyyy`).
  - Compléments : `GET /gaspar/risques?code_insee=33063`, `GET /zonage_sismique?code_insee=33063`.
- Exemple dept 33 : `curl "https://georisques.gouv.fr/api/v1/gaspar/catnat?code_insee=33063&page=1&page_size=100"`.
- Jointure : `code_insee` (commune) ; `latlon` pour RGA/TRI (lon/lat DVF ou BAN).
- Dernière mise à jour des données : non confirmé.
- Pièges :
  1. Ordre `lon,lat` (et non lat,lon). La RGA ne se requête que par point : une requête par bien (ou par centroïde parcelle/IRIS) à 5 appels/s au maximum ; dédupliquer les points avant d'appeler.
  2. Un résultat vide n'est pas "pas de risque" : l'AZI est vide pour Bordeaux et Dunkerque dans les tests alors que des risques inondation existent (TRI Bordeaux). Croiser AZI, TRI et cat-nat. Le lien `next` de pagination pointe vers un hôte interne (`api-georisques.bike-prod.brgm.fr`, en HTTP) : construire soi-même l'URL de la page suivante avec `page=`.

## 4. DRIAS - projections climatiques (Météo-France)

- Portail : https://www.drias-climat.fr (espaces Accompagnement, Découverte, Données et Produits). Commande de données : https://www.drias-climat.fr/commande/ (la page contient les formulaires `creationcompte` et `authenticate`).
- Verdict : pas d'API ni de téléchargement anonyme programmatique confirmé. Le guide de téléchargement DRIAS (PDF 2021, https://www.drias-climat.fr/document/DRIAS-Guide-telechargement_2021-09-21.pdf) indique : la première étape pour télécharger est la création d'un compte, afin de valider les conditions d'utilisation. Compte gratuit : non confirmé (inscription non effectuée). Un "accès simplifié" aux NetCDF d'origine existe depuis le serveur ClimateData du CNRM (URL non confirmée ; la newsletter d'octobre 2025 signale que le catalogue climatedata a changé et peut casser les scans automatisés).
- Contenu confirmé (newsletters DRIAS N7 sept. 2025 et N8 oct. 2025) :
  - Indicateurs TRACC (niveaux de réchauffement) pour la France hexagonale et la Corse : 59 indicateurs en NetCDF dont 13 aussi en CSV sur l'espace Données et Produits ; données de base quotidiennes à 8 km (jeu Explore2-Climat-2022) en NetCDF et CSV.
  - DRIAS-2020 : grille 8 km, correction ADAMONT à partir des observations SAFRAN, scénarios RCP 2.6, 4.5 et 8.5 (résultat de recherche sur la documentation DRIAS-2020 ; non relu à la source).
  - Formats : NetCDF et CSV (sélection personnalisée par période et zone).
- Licence : "Les données mises à disposition sur les portails DRIAS-climat et DRIAS-Eau sont couvertes par la licence Etalab" (https://www.drias-climat.fr/accompagnement/conditions), c'est-à-dire la Licence Ouverte / Open Licence v2.0 selon le lien de la page.
- Fiche data.gouv : https://www.data.gouv.fr/datasets/5dfb22926f44413ada2c54b4 ("DRIAS - projections climatiques pour l'adaptation de nos sociétés", licence `fr-lo`, modifiée le 2023-12-12) : simple lien vers le portail, aucune ressource téléchargeable.
- Alternatives ouvertes vérifiées (sans compte) :
  1. Indicateurs TRACC par territoire, Bretagne uniquement : https://www.data.gouv.fr/datasets/6645ddb23a9c070c371a627a (Observatoire de l'environnement en Bretagne, Licence Ouverte 2.0, modifié le 2026-03-17). Hors pilote : utile seulement comme modèle de format.
  2. Débits futurs Explore2-TRACC par territoire : https://www.data.gouv.fr/datasets/69848339e734f1ba1e7f3217 (RARE, Licence Ouverte 2.0, 2026-02-18) ; hydrologie seule, pas de jours supérieurs à 35 degrés.
  3. Baseline historique sur la maille SAFRAN 8 km : Météo-France "Données changement climatique - SIM quotidienne" https://www.data.gouv.fr/datasets/6569b2c4f1937611d4c8b1a3 (id `6569b2c4f1937611d4c8b1a3`, mensuelle : `65e040c50a5c6872ebebc711`). Ce sont des données passées, pas des projections.
  4. Climadiag Commune (meteofrance.fr) : synthèse PDF par commune pour 2030, 2050 et 2100 ; aucun jeu ouvert Climadiag trouvé sur data.gouv, donc inexploitable en masse. URL exacte de l'outil : non confirmée.
- Recommandation : un humain crée le compte DRIAS gratuit (l'agent ne crée pas de compte) et télécharge en CSV par sélection personnalisée les indicateurs TRACC / DRIAS-2020 pour les 3 départements ; versionner les fichiers dans le dépôt. Si le compte est impossible, ATLAS doit se rabattre sur la baseline SIM + un delta climat tiré de la littérature, déclaré comme hypothèse, ce qui fragilise la projection 2050.
- Jointure : maille SAFRAN 8 km (points lat/lon ou indices de grille) vers commune/IRIS par jointure spatiale (maille la plus proche ou moyenne des mailles intersectant l'IRIS).
- Pièges :
  1. Les indicateurs récents sont organisés par niveaux de réchauffement TRACC et non par RCP et par année : le passage "RCP 4.5/8.5 en 2050" vers "niveau TRACC" doit être justifié ; DRIAS-2020 reste en RCP.
  2. Interface à formulaires ; catalogue modifié en 2025 (transition annoncée comme transparente pour les utilisateurs mais pouvant casser l'automatisation). Prévoir un téléchargement manuel unique et versionné.

## 5. INSEE Filosofi IRIS + Contours-IRIS IGN

### 5a. Filosofi IRIS (revenus, pauvreté, niveau de vie), millésime 2021
- Page : https://www.insee.fr/fr/statistiques/8229323 (paru le 31/07/2024). Le millésime 2021 est le dernier : INSEE indique que le millésime 2022 n'a pas pu être produit (qualité statistique insuffisante des sources, d'après un résumé de recherche web ; non relu sur la page).
- Téléchargements (testés, HTTP 200 pour le fichier DISP) :
  - Revenus disponibles (CSV) : `https://www.insee.fr/fr/statistiques/fichier/8229323/BASE_TD_FILO_IRIS_2021_DISP_CSV.zip` (913 460 o). Contient `BASE_TD_FILO_IRIS_2021_DISP.csv` et `meta_BASE_TD_FILO_IRIS_2021_DISP.csv`.
  - Revenus déclarés (CSV) : `https://www.insee.fr/fr/statistiques/fichier/8229323/BASE_TD_FILO_IRIS_2021_DEC_CSV.zip` (lien présent sur la page, non téléchargé).
  - XLSX : `BASE_TD_FILO_IRIS_2021_DEC_XLSX.zip` et `BASE_TD_FILO_IRIS_2021_DISP_XSLX.zip` (orthographe "XSLX" telle que dans le lien).
- Format : CSV séparateur `;`, décimales à virgule, en-tête observé `IRIS;DISP_TP6021;DISP_INCERT21;DISP_Q121;DISP_MED21;DISP_Q321;...;DISP_GI21;...;DISP_NOTE21` ; 16 026 lignes de données. Clé : `IRIS` (9 caractères, ex. `330630101`, Bordeaux).
- Auth : aucune. Licence : non confirmée sur la page INSEE ; à vérifier (des jeux Filosofi republiés sur data.gouv sont en Licence Ouverte 2.0, ex. https://www.data.gouv.fr/datasets/66fd2924ca43b044d55a7b74).
- Pièges :
  1. Couverture : seulement les IRIS des communes d'au moins 5 000 habitants (10 000 jusqu'au millésime 2019, d'après la recherche web). Les petites communes n'ont aucune ligne : prévoir un repli commune ou carreaux 200 m (Filosofi carroyé 2021 : https://www.insee.fr/fr/statistiques/8735243).
  2. Valeurs arrondies et indicateurs de fiabilité (`DISP_NOTE21`, `DISP_INCERT21`) à exploiter ; virgule décimale à convertir ; le millésime de revenus 2021 est antérieur aux prix DVF récents (2024-2026) : décalage temporel à assumer.

### 5b. Contours-IRIS (IGN)
- Catalogue de téléchargement (testé) : `https://data.geopf.fr/telechargement/resource/CONTOURS-IRIS` (flux Atom, 53 entrées).
- Dernière édition France entière : `CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01` (GeoPackage, EPSG:4326), publiée le 2026-07-03 :
  `https://data.geopf.fr/telechargement/download/CONTOURS-IRIS/CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01/CONTOURS-IRIS_3-0__GPKG_WGS84G_FRA_2026-01-01.7z` (HTTP 200, 88 282 257 o, archive 7z).
- Alternatives : Shapefile France entière `CONTOURS-IRIS_3-0__SHP__FRA_2023-01-01` (mis à jour 2024-03-08) ; métropole Lambert-93 `CONTOURS-IRIS_3-0__SHP_LAMB93_FXX_2024-01-01`. Schéma d'URL `/telechargement/download/CONTOURS-IRIS/{nom}/{nom}.7z` confirmé pour l'édition 2026, non testé pour les autres.
- Auth : aucune. Licence : non confirmée sur data.geopf.fr ; la fiche data.gouv "Contours... Iris" (id `595915ada3a7291dd09c804f`, édition 2024, mise à jour 2025-02-25) indique `lov2` (Licence Ouverte 2.0), mais ses ressources sont des exports d'Île-de-France.
- Pièges :
  1. L'édition 2026 reflète le découpage 2026 alors que Filosofi 2021 utilise celui de 2021 : après fusions de communes, certains codes IRIS ne correspondent plus. Préférer l'édition IGN la plus proche de 2021 (des éditions 2015 à 2020 sont listées dans le catalogue) ou prévoir une table de passage.
  2. Nom exact du champ code IRIS dans le GPKG : non confirmé (archive 7z non téléchargée). Lire le schéma avant de coder la jointure. Extraction : 7-Zip ou py7zr.

## 6. BAN - Base Adresse Nationale

- Jeu : https://www.data.gouv.fr/datasets/base-adresse-nationale/ (licence `lov2` = Licence Ouverte 2.0 d'après les métadonnées ; fréquence "daily" ; fiche modifiée le 2025-05-27).
- CSV par département (testé) : `https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-{dep}.csv.gz`
  - 33 : 27 595 790 o, 727 531 lignes, Last-Modified 2026-11-13. 13 : 18 917 923 o. 59 : 35 609 511 o (Last-Modified 2026-11-13).
  - Exemple : `curl -O https://adresse.data.gouv.fr/data/ban/adresses/latest/csv/adresses-33.csv.gz`
  - Format : CSV séparateur `;`. Colonnes observées : `id;id_fantoir;numero;rep;nom_voie;code_postal;code_insee;nom_commune;code_insee_ancienne_commune;nom_ancienne_commune;x;y;lon;lat;type_position;alias;nom_ld;libelle_acheminement;nom_afnor;source_position;source_nom_voie;certification_commune;cad_parcelles`.
- Géocodage : l'ancienne API a migré. Observé : `https://api-adresse.data.gouv.fr/search/?q=...` répond encore 200 mais avec les en-têtes `deprecation` et `sunset: Sat, 31 Jan 2026 22:59:59 GMT` (date dépassée) et `location: https://data.geopf.fr/geocodage/search/...`. Utiliser la Géoplateforme :
  - Recherche (testée) : `curl "https://data.geopf.fr/geocodage/search?q=8+bd+du+port+33000&limit=1"` renvoie un GeoJSON avec `properties.id` ("33063_7465_00008"), `banId`, `citycode`, `score`, `x`/`y`.
  - Géocodage en masse CSV : `POST https://data.geopf.fr/geocodage/search/csv` (endpoint répond 200 ; usage détaillé non testé). Capacités : https://data.geopf.fr/geocodage/getCapabilities.
  - Limites : en-têtes `ratelimit-limit: 50` et `x-ratelimit-limit-second: 1` observés ; leur interprétation exacte est non confirmée. Auth : aucune.
- Jointure : `id` (BAN) = DPE `identifiant_ban` ; `cad_parcelles` (parcelles séparées par `|`, ex. `33001000ZO0156|33001000ZO0157`) = DVF `id_parcelle` ; `code_insee` commune.
- Pièges :
  1. `cad_parcelles` contient souvent plusieurs parcelles par adresse, et une parcelle porte plusieurs adresses : exploser la liste (`split('|')`), relations plusieurs-à-plusieurs, donc une adresse peut correspondre à plusieurs lignes DVF.
  2. Les `id` BAN peuvent évoluer avec les mises à jour quotidiennes (nouvelles voies, fusions de communes) : figer la date du dump BAN et utiliser la même pour joindre DPE et DVF. Le `banId` (UUID) de la Géoplateforme est distinct de l'`id` composite. Environ 727 k lignes pour la Gironde : lecture par blocs si mémoire limitée.

---

## Synthèse des risques pour ATLAS 2050

1. DRIAS : seul point de blocage réel (compte obligatoire, pas d'API) ; téléchargement manuel unique par un humain.
2. DVF : le chemin par département `latest` est archivé et peut disparaître (annonce de suppression fin novembre 2026) ; basculer dès maintenant sur les fichiers nationaux annuels `full-{année}.csv.gz` et les mettre en cache local.
3. Filosofi : IRIS limités aux communes de 5 000 habitants et plus ; millésime 2021 final (pas de 2022).
4. Géorisques : AZI lacunaire ; combiner RGA, TRI et cat-nat ; 5 appels/s en v1.
5. Licences non confirmées : Filosofi (page INSEE) et Contours-IRIS (IGN) ; à vérifier avant publication.
