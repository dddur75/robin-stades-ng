# Registre des modèles

## Baselines existantes

| Modèle | Version | Statut | Preuve |
|---|---:|---|---|
| Marché dé-viggé proportionnel | 0.1 | `VERIFIED` | test de somme à 1 |
| Marché dé-viggé Shin | 0.1 | `VERIFIED` | utilisé par `probas_justes` |
| Taux de base segmenté | 0.1 | `PARTIAL` | rapports Vague 1/2 |

## Modèles probabilistes Jalon 2

| Modèle | Version | Statut | Usage |
|---|---:|---|---|
| Elo | 1.0 | `SHADOW_READY` | probabilités 1N2 interprétables |
| Poisson | 1.0 | `SHADOW_READY` | buts attendus et 1N2 |
| Dixon-Coles | 1.0 | `SHADOW_READY` | correction faibles scores |
| Consensus Elo–Poisson | 1.0 | `SHADOW_READY` | référence initiale |
| Marché dé-viggé | 1.0 | `SHADOW_READY` | baseline si snapshot disponible |
| Régression logistique | — | `NOT_STARTED` | hors périmètre |
| Gradient boosting | — | `NOT_STARTED` | hors périmètre |
| Ensemble calibré | — | `NOT_STARTED` | hors périmètre |

Tous appliquent un cutoff temporel strict et enregistrent `as_of_time`.
`SHADOW_READY` n'implique pas de validation prospective. Aucun modèle n'est
`PRODUCTION_READY`.

## État prospectif Jalon 4

Seul `MARKET_BASELINE_ONLY` a produit une prédiction live, faute de données
sportives profondes API-Football. Elle reste `SHADOW_ONLY`, versionnée et
rejouable. Aucun modèle n’est promu pendant le burn-in.
