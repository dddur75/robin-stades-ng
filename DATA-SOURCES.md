# Sources de données

Audit initial : 2026-07-24.

## Football-Data.co.uk

Statut : `PARTIAL` — source historique principale actuelle.

- Accès : CSV publics gratuits.
- Usage actuel : résultats, statistiques de match et cotes historiques.
- Couverture locale observée : 36 423 matchs, 9 ligues, 11 saisons, du
  2015-07-31 au 2026-05-24.
- Fraîcheur annoncée par la source : au moins deux mises à jour par semaine.
- Historique annoncé : résultats depuis 1993/94 selon les compétitions, cotes et
  statistiques sur une période plus courte.
- Limite critique : Football-Data signale que les cotes Pinnacle sont devenues
  systématiquement obsolètes depuis le 2025-07-23 et recommande la prudence.
- Licence/conditions : accès gratuit annoncé ; droits de redistribution et
  conservation à clarifier avant toute diffusion publique de données dérivées.
- Décision : conserver pour le prototype et les baselines historiques, sans
  considérer Pinnacle comme une clôture fiable après le 2025-07-23.

Référence officielle :
https://www.football-data.co.uk/data.php

## Understat

Statut : `UNVERIFIED` — enrichissement xG en mode best effort.

- Accès actuel : extraction HTML non officielle dans `agents/agent_understat.py`.
- Couverture visée : cinq grands championnats.
- Données : xG agrégé au niveau match.
- Limites : scraping fragile, schéma non contractuel, absence de SLA et conditions
  de réutilisation non validées dans le dépôt.
- Décision : ne jamais en faire une dépendance bloquante ; remplacer par une source
  contractuelle ou ouverte dont la licence est explicite avant production.

## The Odds API

Statut : `PARTIAL` — source prospective déjà configurée.

- Accès : API JSON v4 ; secret GitHub `ODDS_API_KEY` présent.
- Usage actuel : événements et snapshots de marchés pour neuf compétitions.
- Coût officiel observé le 2026-07-24 : gratuit 500 crédits/mois ; 20 000 crédits
  à 30 USD/mois ; paliers supérieurs disponibles.
- Comptage officiel : coût principalement déterminé par le nombre de marchés et
  de régions demandés ; les réponses exposent les crédits utilisés et restants.
- Garde-fou local : plafond de 15 000 crédits/mois et arrêt si moins de
  500 crédits restent.
- État réel : 86 événements figurent dans le ledger, mais aucun snapshot
  `odds_*.parquet` n'est encore archivé et le compteur local de juillet vaut zéro.
- Décision : conserver en mode prospectif surveillé ; aucune augmentation de plan
  sans validation explicite.

Références officielles :
https://the-odds-api.com/
https://the-odds-api.com/liveapi/guides/v4/

## Politique d'intégration

Toute nouvelle source doit fournir :

- identifiant fournisseur stable ;
- horodatage de collecte et de validité ;
- stockage brut immuable ;
- version du schéma ;
- licence ou conditions vérifiées ;
- limites et coût ;
- table de correspondance des entités ;
- contrôles de couverture, fraîcheur et cohérence.
