# Suivi des coûts

Dernière mise à jour : 2026-07-24.

| Poste | Coût observé | Statut |
|---|---:|---|
| Football-Data.co.uk | 0 | `VERIFIED` |
| Understat | 0 | `UNVERIFIED` |
| The Odds API | formule existante, budget logiciel 450 crédits/mois | `PARTIAL` |
| API-Football | adaptateur prêt, aucune souscription | `READY_NO_KEY` |
| PostgreSQL local/CI | 0, conteneur éphémère | `VERIFIED` |
| Stockage brut local | coût marginal local | `VERIFIED` |
| GitHub Actions | 5 tâches bornées, artefacts 7 à 14 jours | `PARTIAL` |
| Cockpit Sites | déploiement privé, aucun achat | `VERIFIED` |
| Appels IA en production | 0, non intégrés | `VERIFIED` |
| Paris réels | 0, verrouillés | `PRODUCTION_LOCKED` |

Le fournisseur mock, SQLite pour les tests et PostgreSQL 16 en service CI
permettent de vérifier le Jalon 1 sans service distant payant.

Le pipeline The Odds API applique un plafond de 450 crédits mensuels et s'arrête
sous 25 crédits restants. Aucune augmentation de plan ni dépense supplémentaire
n'est autorisée sans décision explicite documentant besoin, alternative gratuite,
coût mensuel et gain attendu.
