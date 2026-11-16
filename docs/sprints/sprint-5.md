# Sprint 5 : le front (Katana Forge)

**Date :** 2026-11-16 · **Statut :** front livré et testé en local (`apps/web`) ; verdict
du Shogun : **PAS ENCORE** (une seule porte non franchie : performance mobile, voir la fin).

## Direction créative (S5.1)

**Métaphore retenue : « l'atlas honnête : le relevé et le blanc ».** Les cartographes
laissaient en blanc ce qu'ils n'avaient pas arpenté. ATLAS 2050 allume ce qui a été mesuré
(ventes DVF agrégées en hexagones H3 d'au moins 5 ventes) et laisse en blanc hachuré,
signé, ce qui ne l'est pas : le climat (DRIAS indisponible), la trajectoire entre la date
de valeur et 2050, la carte 2050 par hexagone.

La métaphore du plan (« l'eau monte, les argiles sèchent, les colonnes s'affaissent ») est
**rejetée** : elle demandait des chiffres climatiques que l'API ne produit pas.

Moments signatures :
1. **Le relevé** (ouverture) : affiche SVG rendue au serveur à partir de la vraie réponse
   `/hex` r7 (1 075 hexagones, 78 714 ventes), découverte d'ouest en est par une ligne
   d'arpentage dorée (CSS, transform seul, 1,3 s). Lisible sans JavaScript.
2. **Le relief se soulève** : au premier geste, MapLibre + deck.gl remplacent l'affiche une
   fois les hexagones dessinés ; la caméra s'incline et les colonnes montent jusqu'au prix
   médian réel (2 s). Sol : contours des communes et des IRIS servis par **notre** Martin,
   teinte des IRIS = exposition RGA (seul risque cartographiable par l'API ; IRIS « inconnue »
   hachurés).
3. **Le bord du temps** : réglette 2021 (2e sem.), 2022, 2023, 2024, 2021 à 2024, puis 2050.
   Les hauteurs passent d'une année réelle à l'autre (transition deck.gl entre deux états
   réels, aucune valeur intermédiaire affichée). À 2050 la carte se couvre de hachures
   « terra incognita » : pas de valeur par hexagone, la projection se fait bien par bien.
4. **La fourchette, pas le chiffre** (fiche) : règle P10-P50-P90 en €/m² (seule unité
   commune à toutes les lignes de l'API), statu quo, rénovation en D, sensibilités « non
   causal » à deux bornes, cartouches hachurés « indisponible (DRIAS) » sans barre ; frise
   date de valeur → 2050 avec le seul calendrier connu (loi Climat et résilience) et la
   mention « aucune trajectoire calculée » ; waterfall SHAP refermé sur la prédiction.
5. **Deux relevés côte à côte** : même bien, deux lieux, même échelle.

## Décisions

| Sujet | Décision | Pourquoi |
|---|---|---|
| Curseur 2025 → 2050 | Remplacé : réglette des années réelles 2021-2024 + 2050 en terra incognita ; dans la fiche, deux états (date de valeur, 2050) et le calendrier légal entre eux | l'API ne projette que l'horizon 2050, bien par bien, et aucun hexagone |
| Couleur des hexagones | Prix (redondant avec la hauteur, classes par quantiles des hexagones affichés), le risque est au sol (RGA par IRIS) | `/hex` ne renvoie aucun risque ; PPRI, TRI et Cat-Nat sont communaux et vont dans la fiche |
| H3HexagonLayer | Remplacé par `SolidPolygonLayer` (+ `h3-js`) | `@deck.gl/geo-layers` tirait 11 vulnérabilités (fflate, image-size, loaders glTF) jamais utilisées ; même rendu, `npm audit --omit=dev` : 0 |
| Fond de carte | Aucun tiers : style construit sur nos tuiles Martin `communes` et `iris` (IGN-INSEE Contours IRIS, Licence Ouverte, vérifiée dans les métadonnées CSW de l'IGN le 2026-11-16), pas de couche texte (aucune police distante) | règle « local, sans clé » ; hors Gironde, la carte est noire : le bord des données est le bord de la carte |
| Accès à l'API | Réécritures Next : `/api/atlas/*` → `:8000`, `/tiles/*` → `:3001` | même origine, pas de CORS à ouvrir ; CSP `connect-src 'self'` |
| Recherche d'adresse | Pas d'autocomplétion BAN dans le navigateur ; communes via `/communes`, adresse en `POST /estimate` (géocodée par l'API) | règle « API locale seulement » ; une adresse ne part jamais dans une URL |
| Waterfall SHAP | Champ `explication` ajouté à l'API (`base_prix_m2`, `autres_pct`, `prix_m2_modele`) | sans base ni reste, 6 facteurs ne se referment pas ; TreeSHAP est additif en log-prix |
| Prix du jour et DPE | La valeur du jour est étiquetée « DPE au mix moyen des ventes » ; l'écart 2050 est dit « effet de la classe X, pas une évolution du marché » | le modèle de prix n'utilise pas le DPE (avertissement de l'API) |
| Affiche | SVG en ligne (7 tracés, un par classe), plus d'animation interne | une image SVG animée se redessine sur le fil principal ; en `<img>` elle devenait l'élément LCP (3,2 s au mobile simulé) ; en ligne, LCP = titre (1,1 s) |
| Hydratation | Carte (1,56 Mo brut) au premier geste ; réglages en `React.lazy` rendu serveur ; formulaire d'estimation monté à l'approche, au premier geste ou au clic « Estimer ici » | JS initial sous 200 kB et tâches longues découpées |
| Worker MapLibre 6 | Copié dans `public/vendor/` au build (`scripts/copy-maplibre-worker.mjs`), déclaré par `setWorkerUrl` | MapLibre 6 cherche son worker à côté de son module, chemin perdu une fois empaqueté |
| Indexation | Page indexable (agrégats d'au moins 5 ventes), `robots.txt` interdit `/api/` et `/tiles/`, l'API reste `noindex` | **à confirmer par le founder** : les conditions DVF interdisent d'indexer « les données » ; les CGU complètes n'ont pas été lues (sources.md §1) |

## Vitesse de l'API

Les lenteurs annoncées (p95 `/hex` r9 ≈ 2 s, `/estimate` ≈ 2,8 s) venaient de la mesure du
sprint 4 (TestClient en processus, juste après un réentraînement). Mesuré ce sprint en HTTP
réel sur uvicorn local : `/hex` r9 Bordeaux p50 54 ms / p95 58 ms (30 appels), r9 sur 0,25
deg² p50 117 / p95 171 ms, `/hex` r7 Gironde p50 84 ms (15 appels), `/estimate` maison G
p50 261 ms, max 340 ms (8 appels). Aucune optimisation côté API n'était donc nécessaire ; le
front charge le r9 par tuiles fixes de 0,5° (aire = plafond de l'API, URL répétables donc
cache HTTP) et affiche un état d'attente pour chaque appel.

## Mesures (build de production, `next start`, Lighthouse 13.6.0 sous Chrome, machine de dev partagée)

| | Perf | A11y | BP | SEO | LCP | TBT | CLS |
|---|---:|---:|---:|---:|---:|---:|---:|
| Mobile, 3 passes | 0,93 / 0,85 / 0,93 | 1 | 1 | 1 | 1,1 s | 310 / 590 / 300 ms | 0 |
| Bureau, 3 passes | 1 / 1 / 1 | 1 | 1 | 1 | 0,3 s | 40 / 40 / 60 ms | 0 à 0,019 |
| Page Next vide (repère du cadre, même machine) | 0,93 / 0,96 | | | | 0,8 s | 340 / 230 ms | |

Poids (gzip niveau 9, `npm run budget`) : **JS initial 173,9 kB** (7 scripts, budget
200 kB), HTML 25,4 kB. Chargés à la demande : carte MapLibre + deck.gl 428 kB, H3 62 kB,
worker MapLibre 147 kB.

## Tests

| Contrôle | Résultat |
|---|---|
| `npm run typecheck` (TS strict, `noUncheckedIndexedAccess`) | propre |
| `npm run lint` (eslint-config-next 16) | propre |
| `npm test` (Vitest, seuil 80 % imposé) | 35 réussis ; couverture de `src/lib` : instructions 90,1 %, branches 81,0 %, fonctions 91,8 %, lignes 90,8 % |
| `npx playwright test` (bureau 1440x900, téléphone 390x844, vraie API, Chrome) | 15 réussis, 1 ignoré (test propre au téléphone, sauté au bureau) ; dernière passe complète 13 réussis et 2 échecs (libellé de test périmé et formulaire monté à l'approche), corrigés puis rejoués : recherche → fiche → 2050 ; filtres et 2050 ; comparaison ; sans JS ; affiche dimensionnée sans JS et sans débordement ; clavier → focus sur la carte ; 2050 au téléphone ; mouvement réduit |
| API (`apps/api`) : ruff, mypy strict, pytest | propres ; 168 réussis (dont 18 d'intégration PostGIS), couverture 98,4 % ; OpenAPI régénéré |
| `npm audit --omit=dev` | 0 vulnérabilité (dev : 1 modérée, minimatch dans la chaîne eslint) |

## Inspection (Kensa, Mamori) et corrections

| # | Constat | Gravité | Correction |
|---|---|---|---|
| K1 | Cartouche 2050 plein cadre au téléphone, hachures invisibles, sous l'en-tête | bloquant | bandeau bas compact sous 960 px (`max-height: 48 %`), texte long masqué ; test e2e « 2050 sur téléphone » |
| K2, M3 | « Soulever le relief » démonté au focus : focus perdu, carte inatteignable au clavier | bloquant | plus d'écoute `focusin` ; le bouton reste jusqu'à la carte prête, le focus passe alors sur le canvas ; test e2e clavier |
| M1 | Sans JS, l'affiche mesurait 0x0 : React sortait la grande frontière Suspense du flux initial | bloquant | Suspense retiré autour de la vue ; test e2e « affiche dimensionnée sans JS » |
| K3, M6 | En-tête qui déborde à 390 px et moins (scrollWidth 398) | majeur | nom masqué visuellement sous 440 px (gardé dans l'étiquette du lien), liens à 44 px |
| K4, K6 | API `/hex` en panne : carte vide ; sol nu avant les colonnes | majeur | l'affiche reste jusqu'aux premiers hexagones dessinés ; en cas d'échec, message dans la vue et bouton « Réessayer » ; légende « données indisponibles » au lieu de « 0 » |
| K5 | « −18,7 % » lu comme une évolution 2025 → 2050 alors que c'est l'effet DPE | majeur | étiquettes « DPE au mix moyen des ventes » et « l'effet de la classe X, pas une évolution du marché » ; test e2e |
| M3 | Canvas deck.gl focusable sans nom ; anneau de focus du canvas rogné | majeur | `tabindex=-1` et `aria-hidden` sur la surcouche ; anneau intérieur |
| M4 | « Voir » et « Estimer ici » perdaient le focus | majeur | focus sur la carte, ou sur le titre de la section d'estimation |
| M6 | Carte collante qui masque le champ focalisé au téléphone (WCAG 2.4.11) | majeur | `scroll-margin-top` sous la carte pour les contrôles de la colonne |
| M2 | Nom accessible de « Estimer ici » sans le texte visible | mineur | « Estimer ici, au centre de l'hexagone N » |
| M8 | Bordures des champs à 1,5:1 (WCAG 1.4.11) | mineur | `--field-border` à 3:1 |
| K7, K8 | Échap vidait la recherche ; position périmée après une nouvelle frappe | mineur | `type="text"` ; sélection effacée à chaque modification |
| K9 | « de Arcachon » | mineur | `deNom()` (élision), testé |
| K10 | Colonnes du Bassin coupées au cadrage final | mineur | marge gauche et zoom réduits |
| K11, M6 | Cibles de 36 à 40 px | mineur | 44 px au doigt (nav, réglette, contrôles MapLibre) |
| K12 | Bouton « Soulever le relief » mort sans JS | mineur | rendu seulement après hydratation |
| K14 | 78 714 (carte) et 78 358 (modèle) sans explication | mineur | note de méthode : 79 649 ventes au gold, la carte montre les hexagones ≥ 5 ventes, le modèle exclut 1 291 maisons de plus d'un hectare (chiffres lus dans `ml/results.json`) |

Vérifié sans défaut par Kensa : la réponse brute de `/estimate` et celle du proxy sont
identiques octet pour octet ; 1 075 hexagones et 78 714 ventes = somme de `/hex` ; aucun
tiret cadratin ni emoji ; messages d'erreur français pour commune inconnue, adresse
introuvable, terrain de 12 000 m², 503, coupure et 502. Mamori : axe-core 0 violation dans
les 4 états (chargé, relief + 2050, fiche, comparaison) ; contrastes AA partout.

## Ouvert

1. **Performance mobile** : médiane 0,93 (plan : ≥ 0,90, tenu ; serment de la Forge :
   ≥ 0,95, non tenu ; une passe à 0,85). La page Next 16 vide fait 0,93 à 0,96 sur la même
   machine : le reste du TBT est le cadre (react-dom) et l'analyse du HTML. À remesurer sur
   une machine propre (CI) au sprint 6.
2. **Indexation** : décision du founder (voir Décisions).
3. Sans JS, les réglages de la carte et le tableau ne s'affichent pas (ils pilotent une
   carte qui demande JS) ; l'affiche, le titre, les chiffres et la méthode se lisent.
4. Limiteur : derrière le proxy Next, tous les clients partagent l'IP 127.0.0.1 (60
   jetons/min). Sans effet en local ; à traiter au déploiement (`X-Forwarded-For` +
   `FORWARDED_ALLOW_IPS`).
5. agg_hex : soustractions multiples r7/r9 (revue sécurité du sprint 4, point 7), toujours
   ouvert : hors du périmètre de ce sprint (dbt).
6. Non vérifié : lecteurs d'écran réels (NVDA, VoiceOver), vrai GPU (les mesures de la
   carte sont en rendu logiciel), défilement tactile réel sur la carte collante.

## Verdict du Shogun (porte du chef-d'œuvre)

1. **Le moment d'arrêt** : quand les colonnes se lèvent de l'affiche, puis quand on pousse
   la réglette sur 2050 et que la carte se couvre de hachures : le site montre ce qu'il ne
   sait pas.
2. **Le sens** : aucune image décorative ; chaque forme est une donnée de l'API (hexagones,
   sol RGA, contours) ou un aveu (hachures DRIAS, « aucune trajectoire calculée »).
3. **La faille** : corrigées (K1 à K14, M1 à M8) ; reste la carte qui met plusieurs secondes
   en rendu logiciel, non mesurée sur vrai GPU.
4. **Le téléphone** : 390 px sans débordement, bandeau 2050 compact, cibles de 44 px.
5. **Sans JS et mouvement réduit** : titre, affiche, chiffres et méthode lisibles ; aucune
   animation qui tourne.
6. **Les budgets** : JS initial 173,9 kB, LCP 1,1 s, CLS ≤ 0,019, bureau 1,0 ; **mobile 0,93
   en médiane, sous le 0,95 du serment.**
7. **La vérité** : chiffres de l'API ou de `ml/results.json`, recoupés par Kensa.

Ce qui tient : le concept, la vérité, l'accessibilité, le bureau. Ce qui ne tient pas : le
0,95 mobile, non atteint ici. **PAS ENCORE.**
