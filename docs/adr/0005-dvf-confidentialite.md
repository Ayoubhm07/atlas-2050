# ADR 0005 — Confidentialité des données DVF

**Statut :** accepté — 2026-11-15

## Contexte
DVF est publiée sous conditions : interdiction de ré-identifier les personnes et
d'indexer les données par les moteurs de recherche externes.

## Décision
- L'API ne renvoie jamais une transaction isolée avec son adresse : agrégats d'au
  moins 5 ventes, ou estimation par le modèle.
- `robots.txt` et en-tête `X-Robots-Tag: noindex` sur toutes les routes de données.
- Aucune donnée personnelle (nom, date de naissance) n'entre dans le pipeline (DVF
  n'en contient pas ; on le vérifie au contrat de données).

## Conséquences
La fiche « bien » affiche une estimation, pas le prix de vente réel d'un voisin.
