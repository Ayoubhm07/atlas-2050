# ADR 0004 — Projection 2050 en fourchettes, jamais en chiffre sec

**Statut :** accepté — 2026-11-15

## Contexte
Personne ne connaît le prix d'une maison en 2050. Un chiffre unique serait faux et
indéfendable.

## Décision
Valeur projetée = prix estimé actuel × facteurs de décote, où :
- chaque facteur (zone inondable, argiles, chaleur, étiquette DPE) est estimé sur les
  données réelles (SHAP + analyses avant/après Cat-Nat), avec intervalle bootstrap ;
- l'évolution de l'exposition vient des projections climatiques (RCP 4.5 / 8.5) ;
- le calendrier de la loi Climat et résilience s'applique aux logements loués
  (G : 2025, F : 2028, E : 2034).

Le résultat affiché est toujours une fourchette, avec la méthode et les limites en lien.
Hors inflation : tout est exprimé en euros constants.

## Conséquences
`docs/methodology.md` est un livrable à part entière, présenté en soutenance.
