# ADR 0003 — Modèle LightGBM avec validation spatiale et temporelle

**Statut :** accepté — 2026-11-15

## Contexte
Les prix immobiliers sont fortement autocorrélés dans l'espace. Une validation
aléatoire classique gonfle les scores (le voisin d'un bien de test est dans le train).

## Décision
- Baseline : régression linéaire régularisée (Ridge) sur log(prix/m²).
- Modèle : LightGBM + Optuna.
- Validation : `GroupKFold` par commune + test final temporel (train ≤ 2023, test 2024).
- Features de voisinage calculées uniquement sur des ventes antérieures (pas de fuite).
- SHAP pour l'explication globale et par bien ; MLflow pour le suivi.

## Conséquences
Scores plus modestes mais honnêtes et défendables devant le jury.
