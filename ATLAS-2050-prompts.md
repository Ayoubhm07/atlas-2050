# ATLAS 2050 — « Combien vaudra cette maison quand le climat aura changé ? »

> Projet IPSSI Open Data — Sujet 4 (libre), tous les critères couverts et dépassés.
> Équipes : `/war-room` (data, backend, ML, sécurité, QA, devops) + `/katana-forge` (design, animation, front).

---

## 0. Pourquoi ce sujet écrase les 3 autres

| Critère prof | Ce qu'ATLAS 2050 livre |
|---|---|
| Open Data (min 2) | **6 sources publiques françaises** croisées à l'adresse près |
| BDD | PostgreSQL + **PostGIS** (géospatial) + DuckDB/Parquet (lakehouse) |
| Architecture Big Data | Airflow, PySpark, Parquet partitionné, ~30 M lignes |
| Analyse + dataviz | Carte 3D deck.gl, notebooks, rapport Evidence/Power BI |
| Modèle de prédiction | Prix au m² (LightGBM + SHAP) **+ projection 2050 sous scénarios climatiques GIEC** |
| Filtres | Commune, type de bien, DPE, risque, scénario, horizon |

**La question que personne ne pose :** le marché immobilier français ne prix­e pas encore le risque climatique (inondation, retrait-gonflement des argiles, canicule) ni l'interdiction de louer les passoires thermiques (loi Climat 2025/2028/2034). ATLAS 2050 calcule la **« décote climatique »** de chaque bien : la valeur aujourd'hui, la valeur projetée en 2030/2050, et *pourquoi* (explication SHAP lisible).

Utilisateurs : acheteur particulier, banque (risque de crédit), collectivité (plan d'adaptation). C'est un vrai produit, pas un TP.

### Sources Open Data (toutes gratuites, sans clé ou avec clé gratuite)
1. **DVF** — Demandes de Valeurs Foncières (data.gouv.fr) : toutes les ventes immobilières depuis 2019 (~20 M lignes).
2. **DPE ADEME** — Diagnostics de performance énergétique (API data.ademe.fr, ~10 M).
3. **Géorisques** (BRGM, API) : inondation (PPRI, TRI), retrait-gonflement argiles, sismicité, Cat-Nat historiques.
4. **DRIAS / Météo-France** : projections climatiques (jours > 35 °C, sécheresse) par scénario RCP 4.5 / 8.5.
5. **INSEE** (Filosofi, IRIS) : revenus, démographie par quartier.
6. **BAN** — Base Adresse Nationale : géocodage et jointure de tout le reste.

> Garde-fou : si une source change d'API ou de licence, le sprint 1 vérifie chaque endpoint, sa licence (Licence Ouverte Etalab / ODbL) et sa date avant toute ligne de code. Aucun chiffre inventé : chaque KPI affiché cite sa source et sa date.

---

## 1. LE MASTER PROMPT (à coller tel quel pour lancer la Légion)

```
/legends-league

MISSION : ATLAS 2050 — projet Open Data IPSSI (sujet 4 libre), niveau produit élite.

CONTEXTE
Le prof exige : open data (≥2 sources), web app, BDD, analyse + dataviz, modèle de
prédiction, filtres, architecture Big Data (Airflow, PySpark, Kafka… cités en exemple).
Livrable : repo GitHub + soutenance 15–20 min + 5 min de questions.
Nous visons très au-dessus : un produit que le jury veut utiliser.

PRODUIT
Pour chaque logement de France métropolitaine (commencer par 3 départements pilotes :
Gironde 33, Bouches-du-Rhône 13, Nord 59 — contrastés en risques), ATLAS 2050 affiche :
- le prix estimé aujourd'hui (modèle entraîné sur DVF) ;
- l'exposition climatique (Géorisques + DRIAS) et la contrainte DPE (loi Climat) ;
- la valeur projetée 2030 / 2050 sous RCP 4.5 et RCP 8.5 = « décote climatique » ;
- l'explication SHAP en langage clair (« −11 % : zone argile aléa fort + DPE G »).

SOURCES (vérifier endpoint, licence, fraîcheur avant code) :
DVF, DPE ADEME, Géorisques, DRIAS, INSEE Filosofi/IRIS, BAN.

STACK IMPOSÉE (justifier tout écart dans un ADR)
- Ingestion/orchestration : Apache Airflow (docker-compose), DAG par source, idempotents.
- Traitement : PySpark (DVF+DPE) → Parquet partitionné (département/année) = couche bronze/silver/gold.
- Analytique : DuckDB sur Parquet ; dbt pour les modèles gold + tests de données.
- BDD service : PostgreSQL 16 + PostGIS, index GIST, tuiles vectorielles (Martin ou pg_tileserv).
- ML : LightGBM + Optuna, validation spatiale (GroupKFold par commune, pas de fuite),
  SHAP, MLflow pour le suivi. Baseline linéaire obligatoire pour comparer.
- API : FastAPI, Pydantic v2, pagination, rate limiting, OpenAPI.
- Front : Next.js 15 + TypeScript strict + MapLibre GL + deck.gl (hexagones H3 3D),
  Tailwind, animations par /katana-forge.
- Qualité : pytest ≥80 % sur pipeline/API, Playwright E2E, GitHub Actions CI, Lighthouse ≥90.

RÉPARTITION
- War Room : board (arbitrages), data engineer, ML engineer, backend, sécurité, QA, devops.
- Katana Forge : métaphore visuelle, storyboard, design system, carte 3D, animations, a11y.
- Trésor : non concerné (pas d'argent), sauf juriste pour vérifier licences Open Data et RGPD
  (DVF contient des données sensibles : interdiction de ré-identifier des personnes,
  respecter les conditions d'usage DVF, pas d'indexation par moteurs des adresses).

RÈGLES
1. Vérité verrouillée : aucun chiffre sans source + date. Pas de données fictives en prod.
2. Travail en 6 sprints (plan ci-dessous). Chaque sprint finit par : démo, tests verts,
   revue adverse (katana-kensa + code-reviewer), journal de décision.
3. Je suis le seul auteur des commits (pas de Co-Authored-By). Tu ne pousses rien sans moi.
4. Si une source est inaccessible, tu le dis et tu proposes un remplacement sourcé —
   tu n'inventes jamais.

LIVRABLE DE CETTE PREMIÈRE RÉPONSE
- Vérification des 6 sources (tableau : URL, licence, volume, fraîcheur, piège).
- Architecture (diagramme Mermaid) + 5 ADR courts.
- Backlog découpé en 6 sprints avec critères d'acceptation.
- Risques top 5 et parade.
Puis tu attends mon GO pour le sprint 1.
```

---

## 2. LES SPRINTS ET LEURS PROMPTS

Chaque sprint = un prompt de lancement + des prompts d'exécution + un prompt de clôture. Les coller dans l'ordre.

### Sprint 0 — Cadrage & fondations (½ jour)

**S0.1 — Repo et socle**
```
/war-room Sprint 0 ATLAS 2050. Crée le monorepo :
apps/web (Next.js), apps/api (FastAPI), pipelines/ (Airflow DAGs + PySpark jobs),
dbt/, ml/, infra/ (docker-compose : postgres-postgis, airflow, mlflow, martin), docs/adr/.
Makefile (make up, make ingest, make train, make test). CI GitHub Actions : lint (ruff,
eslint), types (mypy, tsc), tests. .env.example sans aucun secret. README avec schéma.
Critère : `make up` lance tout en local sur Windows (Docker Desktop) en < 5 min.
```

**S0.2 — Contrat de données**
```
Écris docs/data-contract.md : pour chaque source, schéma attendu, clé de jointure
(id parcelle, code INSEE, IRIS, coordonnées BAN), règles de qualité (nulls, doublons,
prix aberrants DVF : ventes à 1 €, lots multiples), et la stratégie de jointure spatiale.
Cite chaque règle avec la doc officielle de la source.
```

### Sprint 1 — Ingestion Big Data (bronze → silver)

**S1.1 — DAGs Airflow**
```
/war-room data engineer. Un DAG Airflow par source (DVF, DPE, Géorisques, DRIAS, INSEE, BAN),
idempotent, rejouable, avec retries + backoff, téléchargement en streaming, checksum,
stockage brut en bronze/ (Parquet, partition dept/année). Respecte les quotas des API
(throttle). Tests : un test par DAG sur un échantillon fixture.
```

**S1.2 — Nettoyage PySpark**
```
Jobs PySpark bronze → silver : DVF (filtrer mutations « Vente », dédoublonner multi-lots,
prix/m² par bien, retirer outliers par IQR par commune), DPE (normaliser classes A–G,
date), géocodage BAN. Écris un rapport de qualité automatique (lignes in/out, % rejet par
règle) dans docs/quality/. Mesure et note le temps d'exécution.
```

**S1.3 — Clôture sprint 1**
```
/war-room QA + code-reviewer : vérifie les volumes vs chiffres officiels de chaque source
(écart > 2 % = bloquant), tests verts, rapport qualité. Liste ce qui casse. Journal de décision.
```

### Sprint 2 — Modélisation de données & BDD géospatiale (gold)

**S2.1 — dbt + PostGIS**
```
/war-room data + database-reviewer. Modèles dbt gold : fact_transactions, dim_bien,
dim_commune, dim_iris, fact_risques (par parcelle), fact_climat (par maille DRIAS → IRIS).
Jointure spatiale PostGIS (ST_Intersects, index GIST). Indexation H3 (résolutions 7 et 9).
Tests dbt (unique, not_null, relationships, accepted_values). EXPLAIN ANALYZE sur les
5 requêtes de l'API : chacune < 100 ms.
```

**S2.2 — Exploration analytique**
```
Notebook docs/analysis/eda.ipynb : distribution prix/m², effet DPE sur le prix
(« valeur verte »), effet Cat-Nat passé sur le prix après sinistre (analyse avant/après),
corrélations risques × prix × revenus INSEE. Chaque graphique a une phrase de conclusion.
Ce notebook nourrit la soutenance.
```

### Sprint 3 — Le modèle (cœur de la valeur)

**S3.1 — Modèle de prix**
```
/war-room ML engineer. Prédire le prix/m² DVF.
- Baseline : régression linéaire régularisée.
- Modèle : LightGBM + Optuna. Features : surface, pièces, type, DPE, H3 voisinage
  (prix médian lissé des k voisins, sans fuite temporelle), revenus IRIS, risques.
- Validation SPATIALE (GroupKFold par commune) + split temporel (train ≤ 2023, test 2024).
- Métriques : MAE, MAPE, R², par département. MLflow pour tout.
- SHAP global + local. Rapport ml/report.md avec matplotlib.
Bloquant si le modèle ne bat pas la baseline de façon significative.
```

**S3.2 — Projection 2050 (décote climatique)**
```
Construis le module de projection, documenté et honnête :
1. Effet prix estimé des risques et du DPE à partir des données (coefficients SHAP /
   analyses avant-après Cat-Nat du sprint 2), avec intervalles de confiance (bootstrap).
2. Évolution des expositions sous RCP 4.5 / 8.5 (DRIAS) et calendrier loi Climat
   (G interdit à la location 2025, F 2028, E 2034).
3. Valeur projetée = prix actuel × facteurs, avec fourchette, jamais un chiffre sec.
Écris docs/methodology.md : hypothèses, limites, ce que le modèle NE dit PAS.
```

**S3.3 — Revue adverse ML**
```
rs-sage : attaque le modèle. Cherche fuite de données, sur-apprentissage spatial,
biais (zones rurales sous-représentées), hypothèses de projection fragiles.
Classe bloquant/majeur/mineur. Corrige les bloquants.
```

### Sprint 4 — API

**S4.1 — FastAPI**
```
/war-room backend + security-reviewer. Endpoints :
GET /communes?q= (recherche), GET /hex?bbox&res&filters (agrégats H3),
GET /estimate?address|lat,lon + caractéristiques (prix, risques, projection, SHAP),
GET /tiles/{z}/{x}/{y} via Martin. Enveloppe de réponse {success,data,error,meta}.
Pydantic, rate limiting, cache (ETag + Redis optionnel), CORS strict, pas d'adresse
nominative exposée (agrégation minimale de 5 transactions — règle DVF).
Tests intégration ≥ 80 %. OpenAPI publié.
```

### Sprint 5 — Le front de banger (Katana Forge)

**S5.1 — Direction créative**
```
/katana-forge Mission ATLAS 2050.
Métaphore centrale proposée : « la France vue depuis 2050 » — une carte de relief sombre
où la valeur des territoires se soulève en hexagones de lumière, puis un curseur du temps
2025 → 2050 fait monter l'eau, sécher les argiles, rougir la chaleur, et les colonnes
s'affaissent. Le visiteur VOIT la décote climatique.
Shogun : valide ou remplace la métaphore. Sensei : storyboard seconde par seconde
(ouverture, recherche d'adresse, fiche bien, comparaison scénarios, méthodo).
Sumi : système visuel (typo, palette accessible pour risques, mode sombre natif),
crédits de toute image. Données réelles de l'API uniquement, jamais de placeholder.
```

**S5.2 — Construction**
```
Tetsu : Next.js + MapLibre + deck.gl (H3HexagonLayer 3D, extrusion = prix, couleur =
risque), barre de recherche d'adresse (BAN autocomplete), filtres (type, DPE, risque,
scénario RCP, horizon 2030/2050), fiche bien avec jauge de décote + waterfall SHAP,
mode comparaison deux adresses. Kaze : transition du curseur temporel (interpolation
des hauteurs), ouverture cinématographique < 2,5 s, reduced-motion complet.
Budgets : LCP < 2,5 s, JS initial < 200 kB, carte chargée en différé.
```

**S5.3 — Garde & critique**
```
Mamori : a11y (clavier sur la carte, alternative tableau aux données carte), mobile natif,
Lighthouse ≥ 90 partout, chiffres exacts. Kensa : revue adverse image par image, tests
au clic/doigt/clavier. Shogun : verdict « chef-d'œuvre ou pas encore ». Boucle jusqu'au oui.
```

### Sprint 6 — Industrialisation, déploiement & soutenance

**S6.1 — Prod**
```
/war-room devops. Déploiement : front Vercel, API + PostGIS sur Railway/Render/Fly
(données gold seulement, dump allégé des 3 départements). E2E Playwright sur les
3 parcours critiques (recherche → fiche → scénario 2050 ; filtres carte ; comparaison).
Full test run, coverage, Lighthouse en CI. README final avec captures, GIF, schéma,
commandes de reproduction, licences des données.
```

**S6.2 — Soutenance 18 min**
```
Construis le deck (slides) :
1. Accroche (0:00–1:30) : démo live — on tape une vraie adresse, la maison perd X % en 2050.
2. Problème & pourquoi c'est inédit.
3. 6 sources Open Data, architecture Big Data (schéma).
4. Pipeline & qualité (chiffres réels : lignes, temps, % rejet).
5. Insights de l'EDA (3 graphiques forts).
6. Modèle : baseline vs LightGBM, validation spatiale, SHAP.
7. Projection 2050 : méthode ET limites (le jury respecte l'honnêteté).
8. Démo produit complète. 9. Sécurité/RGPD/licences. 10. Et après.
+ Annexe : 10 questions pièges probables du jury avec réponses.
Chaque chiffre du deck renvoie à un fichier du repo.
```

**S6.3 — Revue finale**
```
/elite-audit sur l'URL déployée + le repo. Corrige bloquants et majeurs.
Vérifie : git log sans aucune mention Claude/Anthropic/Co-Authored-By.
```

---

## 3. Questions du jury à anticiper (déjà préparées)
- « Votre projection 2050 est-elle fiable ? » → fourchettes, méthodo, limites assumées.
- « Pourquoi PySpark si DuckDB suffit ? » → volume 30 M lignes, scalabilité nationale, et benchmark des deux dans le repo.
- « Fuite de données dans le modèle ? » → validation spatiale + temporelle, démontrée.
- « RGPD sur DVF ? » → agrégation ≥ 5 transactions, pas d'adresse nominative, conditions d'usage DVF respectées.
