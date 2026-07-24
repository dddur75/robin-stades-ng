# Politique temporelle des données

Statut : `VERIFIED` pour les contrats du jalon 1
Fuseau canonique : UTC

## Instants distincts

| Instant | Définition |
|---|---|
| `fixture_created_at` | première observation de l'existence du match |
| `fixture_kickoff_at` | coup d'envoi planifié dans la version du calendrier |
| `data_observed_at` | instant auquel la donnée était vraie ou visible à la source |
| `data_ingested_at` | instant de réception par Robin |
| `prediction_generated_at` | instant d'émission immuable d'une prédiction |
| `odds_observed_at` | instant affiché ou reçu pour une cote |
| `lineup_confirmed_at` | instant de publication d'une composition confirmée |
| `result_confirmed_at` | instant de confirmation du résultat |

Un timestamp sans fuseau est refusé par les nouveaux contrats. L'heure locale du
match est conservée séparément pour l'affichage et les règles locales.

## Invariant point-in-time

Une observation n'est utilisable pour une feature que si :

```text
data_observed_at < as_of_time
```

L'égalité est refusée. `calculated_at` peut être postérieur à `as_of_time`, mais la
feature conserve sa photographie et ses versions :

```text
feature_name
entity_id
fixture_id
value
as_of_time
calculated_at
source_version
feature_version
quality_status
```

Une prédiction conserve exactement les versions de features et sources utilisées.
Une correction tardive crée une nouvelle version ; elle ne réécrit jamais la
prédiction historique.

## Matchs simultanés et données legacy

Football-Data ne fournit pas toujours une heure fiable. Le moteur legacy traite
donc tous les matchs d'une même date comme simultanés :

1. calcul de tous les contextes sur l'état pré-date ;
2. gel des features ;
3. application des résultats du batch.

Cette politique est conservatrice : elle peut ignorer une information devenue
disponible plus tôt dans la journée, mais ne peut pas injecter un résultat
simultané.

## Passe globale arbitre

Les historiques arbitre sont parcourus globalement par date, toutes ligues
confondues, puis séparés en trois variables :

- `referee_global_history` ;
- `referee_competition_history` ;
- `referee_season_history`.

Le signal legacy `ARBITRE_SEVERE` est explicitement l'historique compétition. Le
global et la saison sont exposés sous des noms distincts. Les matchs du même batch
ne s'alimentent jamais entre eux et les statistiques cartes manquantes ne sont pas
ajoutées à l'historique.

## Reports, annulations et corrections

- report : nouvelle version du fixture avec un nouveau `kickoff_at` ;
- annulation : statut `CANCELLED`, historique conservé ;
- interruption : statut distinct à introduire avec règle fournisseur ;
- correction de score : nouvelle version du résultat et nouveau règlement lié au
  précédent ;
- changement de calendrier : aucune mutation d'une prédiction déjà émise ;
- données tardives : versionnées avec leurs deux instants `observed` et `ingested`.

## Tests adversariaux

La suite vérifie :

- résultat futur d'une autre ligue ;
- match simultané ;
- arbitre multi-ligues et multi-saisons ;
- faible échantillon, arbitre inconnu et cartes manquantes ;
- timestamp naïf ou observation non strictement antérieure ;
- règlement corrigé avec `result_version` supérieur.
