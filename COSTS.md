# Suivi des coûts

## Jalon 5.1 — cadence mesurée

Le pilote a consommé 1 354 appels sans achat supplémentaire. La cible
`ACCELERATED_SAFE` est 30 000 appels/jour avec 5 000 appels de réserve. Les ETA
opérationnelles sont trois jours pour la priorité A, huit jours pour la
priorité B et dix jours pour le périmètre complet. GitHub Actions reste dans
les capacités incluses ; aucun stockage objet n’est souscrit automatiquement.

## Jalon 5 — budget API-Football séparé

Le quota quotidien API-Football n’est jamais mélangé au quota mensuel The Odds
API. Le mode de backfill est `ACCELERATED_SAFE`, avec réserve minimale de 5 000 appels.
Le pilote Ligue 1 2025 a consommé 1 354 appels et conservé une réserve très
supérieure aux 100 appels configurés. Une extrapolation volontairement simple
donne environ 10 832 appels pour huit saisons de Ligue 1, 32 496 pour six
compétitions sur quatre saisons et 64 992 pour six compétitions sur huit
saisons. Le plan réel et le cache réduiront ces bornes.

Le stockage supplémentaire n’est pas acheté automatiquement. Voir
`docs/costs/API-FOOTBALL-BACKFILL-FORECAST.md`.

Dernière mise à jour : 2026-07-24.

| Poste | Coût observé | Statut |
|---|---:|---|
| Football-Data.co.uk | 0 | `VERIFIED` |
| Understat | 0 | `UNVERIFIED` |
| The Odds API | 8 crédits consommés, 19 992 restants | `LIVE_PIPELINE_VERIFIED` |
| API-Football | 1 354 appels pilote ; quota quotidien 150 000 ; coût additionnel 0 | `LIVE_PIPELINE_VERIFIED` |
| Neon PostgreSQL | 0 USD ; 11 943 936 octets, soit 2,39 % de 0,5 GB | `CONNECTED_AND_PERSISTED` |
| PostgreSQL local/CI | 0, base SQLite/serveur éphémère | `VERIFIED` |
| Stockage brut local | coût marginal local | `VERIFIED` |
| GitHub Actions | 5 tâches bornées, 2 artifacts / 29 939 octets / 30 jours | `VERIFIED` |
| Cockpit Sites | déploiement privé, aucun achat | `VERIFIED` |
| Appels IA en production | 0, non intégrés | `VERIFIED` |
| Paris réels | 0, verrouillés | `PRODUCTION_LOCKED` |

## Décision de stockage Jalon 4

Neon PostgreSQL est actif sur le plan Free : 0,5 GB par projet et
100 CU-heures mensuelles selon la
[tarification Neon](https://neon.com/pricing). Le plan Launch facture à l’usage
et affiche un exemple typique d’environ 15 USD/mois pour une charge intermittente
de 1 GB. Aucun passage payant n’est requis au volume actuel.

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

## Activation historique post-fusion

- lot `30150002144` : 99 appels API-Football, 0 erreur, 0 HTTP 429 ;
- quota restant observé : 149 895, réserve protégée : 5 000 ;
- stockage `historical-data` après réparation et qualité : 34 657 495 octets ;
- projection recalculée après expansion des tâches : environ 45,7 MB ;
- seuil warning : 750 MB ; seuil de pause : 900 MB ;
- cadence conservée : 30 000 appels/jour, sans montée automatique ;
- coût additionnel facturé par le système : 0 ;
- aucun achat de stockage ni changement de plan.

## Forecast complet Jalon 5.2

La projection budgétaire inclut maintenant les appels latents par fixture,
équipe et page, en plus des tâches déjà matérialisées. Les scénarios bas,
central et haut utilisent les cardinalités de compétition et les pages
réellement observées.

La cadence reste 30 000 appels/jour avec une réserve incompressible de 5 000.
Une hausse à 45 000 ou 60 000 nécessite une PR distincte, zéro HTTP 429, moins
de 1 % d’erreurs, une qualité temporelle verte, aucun impact live et un gain
calendaire démontré. Aucun achat ni hausse n’est automatique.

Mesure Jalon 5.2 : le lot `30154099512` a consommé 2 500 appels et laissé
147 395 appels, sans HTTP 429 ni erreur. La croissance physique durable
observée est de 14 292 000 octets, soit 5 716,8 octets par appel. Ce taux sert
de plancher au forecast de capacité.

| Scénario | Appels restants | ETA | Stockage projeté restauré |
|---|---:|---:|---:|
| Bas | 47 417 | 1,58 j | 227 877 811 octets |
| Central | 63 313 | 2,11 j | 427 181 466 octets |
| Haut | 69 977 | 2,33 j | 665 300 478 octets |

La cadence reste 30 000 appels/jour. Le scénario haut demeure sous 750 MB ;
aucun achat, changement de plan ou hausse de cadence n’est autorisé
automatiquement.

## Coût marginal Jalon 6

La Data Factory, les calibrations et les backtests relisent le cache durable :
0 appel API-Football et 0 crédit The Odds API. DuckDB, Polars et NumPy tournent
dans des jobs GitHub bornés. Les artefacts régénérables sont bornés afin de
contenir les petits fichiers et le stockage dérivé.

Le store long est borné à 16 joueurs par équipe et par cutoff ; les agrégats
d'équipe conservent 18 candidats pour le onze et le banc. Les seuils restent
750 MB warning et 900 MB pause. Le scénario haut doit inclure les artefacts
dérivés avant toute poursuite ; aucun stockage n'est acheté automatiquement.

## Coût du Jalon 7

L'arène, le replay, la calibration, le bootstrap, les ablations et le cockpit
consomment `0` appel fournisseur et `0` crédit. La preuve durable reste
`SAFE` à environ 273,5 MB; warning 750 MB, pause 900 MB. La projection centrale
est ~892,5 MB et la haute ~1 311,9 MB : le garde-fou
stoppera les nouvelles écritures avant ce seuil, sans achat automatique.

## Coût du Jalon 8

La validation externe relit exclusivement `historical-data` :
0 appel API-Football, 0 crédit The Odds API. Sur la preuve locale réelle,
les artefacts analytiques font passer le stockage de 361 005 947 à
364 477 070 octets, soit +3 471 123 octets. Le statut reste `SAFE`.

Warning : 750 000 000 octets. Pause : 900 000 000 octets. Aucun stockage n’est
acheté automatiquement et aucune cadence fournisseur n’est modifiée.

## Budget Jalon 9

API-Football conserve 30 000 appels/jour et 5 000 de réserve. Football-Data est
une archive publique sans crédit fournisseur. The Odds API historique est
plafonnée à 500 crédits et démarre avec un dry-run à zéro crédit. Aucun bucket
R2 ni abonnement n’est créé automatiquement.

Mesure durable Jalon 9 : 474 143 947 octets; projection gates critiques
634 143 947; plan complet 894 143 947; plan complet avec marché 939 143 947.
Le seuil haut de 900 MB impose `OBJECT_STORAGE_REQUIRED`.
