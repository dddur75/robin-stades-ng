# Suivi des coûts

Dernière mise à jour : 2026-07-24.

| Poste | Coût observé | Statut |
|---|---:|---|
| Football-Data.co.uk | 0 | `VERIFIED` |
| Understat | 0 | `UNVERIFIED` |
| The Odds API | 8 crédits consommés, 19 992 restants | `LIVE_PIPELINE_VERIFIED` |
| API-Football | adaptateur prêt, aucune souscription | `READY_NO_KEY` |
| PostgreSQL local/CI | 0, conteneur éphémère | `VERIFIED` |
| Stockage brut local | coût marginal local | `VERIFIED` |
| GitHub Actions | 5 tâches bornées, 2 artifacts / 29 939 octets / 30 jours | `VERIFIED` |
| Cockpit Sites | déploiement privé, aucun achat | `VERIFIED` |
| Appels IA en production | 0, non intégrés | `VERIFIED` |
| Paris réels | 0, verrouillés | `PRODUCTION_LOCKED` |

Le fournisseur mock, SQLite pour les tests et PostgreSQL 16 en service CI
permettent de vérifier le Jalon 1 sans service distant payant.

Le pipeline applique un plafond logiciel de 1 000 crédits mensuels et préserve
une réserve de 4 000 crédits, soit 20 % de la limite observée. La prévision
prudente est de 720 crédits/mois : 40 matchs, 9 fenêtres, 2 crédits. Détails dans
`docs/costs/LIVE-QUOTA-FORECAST.md`.

Aucune augmentation de plan ni dépense supplémentaire n'est autorisée sans
décision explicite documentant besoin, alternative gratuite, coût mensuel et
gain attendu.
