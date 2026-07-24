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

## Décision de stockage Jalon 4

Neon PostgreSQL est recommandé : démarrage gratuit, mise en veille automatique,
pooling et restauration temporelle. Le plan Free fournit 0,5 Go par projet et
100 CU-heures mensuelles ; le plan Launch facture à l’usage et représente
environ 15 USD/mois pour une petite base intermittente autour de 1 Go.

Volume Ligue 1 estimé : 306 matchs × 9 fenêtres × environ 90 cotes, soit
0,4–0,8 Go par saison après données brutes, lignes normalisées et index.
Supabase Free est moins adapté au burn-in continu car les projets inactifs
peuvent être suspendus ; Render Free expire ses bases PostgreSQL après 30 jours.
Le pont `shadow-data` coûte 0 € mais reste transitoire.

Le fournisseur mock, SQLite pour les tests et PostgreSQL 16 en service CI
permettent de vérifier le Jalon 1 sans service distant payant.

Le pipeline applique un plafond logiciel de 1 000 crédits mensuels et préserve
une réserve de 4 000 crédits, soit 20 % de la limite observée. La prévision
prudente est de 720 crédits/mois : 40 matchs, 9 fenêtres, 2 crédits. Détails dans
`docs/costs/LIVE-QUOTA-FORECAST.md`.

Aucune augmentation de plan ni dépense supplémentaire n'est autorisée sans
décision explicite documentant besoin, alternative gratuite, coût mensuel et
gain attendu.
