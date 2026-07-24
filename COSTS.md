# Suivi des coûts

Dernière mise à jour : 2026-07-24.

| Poste | Coût observé | Statut |
|---|---:|---|
| Football-Data.co.uk | 0 | `VERIFIED` |
| Understat | 0 | `UNVERIFIED` |
| The Odds API | aucune nouvelle souscription | `PARTIAL` |
| PostgreSQL local/CI | 0, conteneur éphémère | `VERIFIED` |
| Stockage brut local | coût marginal local | `VERIFIED` |
| GitHub Actions | non calculé, workflow borné à 15 min | `PARTIAL` |
| Appels IA en production | 0, non intégrés | `VERIFIED` |
| Paris réels | 0, verrouillés | `PRODUCTION_LOCKED` |

Le fournisseur mock, SQLite pour les tests et PostgreSQL 16 en service CI
permettent de vérifier le Jalon 1 sans service distant payant.

L'archive The Odds API conserve un plafond de 15 000 crédits mensuels et s'arrête
sous 500 crédits restants. Aucune augmentation de plan ni dépense supplémentaire
n'est autorisée sans décision explicite documentant besoin, alternative gratuite,
coût mensuel et gain attendu.
