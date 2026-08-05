# Catalogue des grains football V1

## Autorité et périmètres

Le fichier autoritatif est
`configs/data/football-grain-catalog-v1.json`. Le générateur des preuves P0
consomme directement ce catalogue et inclut sa définition dans chaque
`definition_hash`. L'ancien résumé de grains conservé dans le contrat de
dénominateur est non autoritatif et n'est jamais lu par l'oracle.

Deux périmètres ne doivent jamais être agrégés ensemble :

- `P0_2020_2025` : cinq compétitions, six saisons et seize familles ; seul
  périmètre utilisé par les gates ;
- `EXTENDED_ALL_AVAILABLE` : saisons anciennes, futures, partielles, ou
  observations explicitement incomplètes ; inventaire non bloquant.

Une observation dans les dimensions P0 mais explicitement partielle est
classée dans le corpus étendu. Elle ne diminue donc pas artificiellement un
taux P0 et ne peut pas fermer une cellule.

## Grains canoniques

| Grain | Clé distincte | Source | Classe temporelle | Dénominateur attendu |
|---|---|---|---|---|
| Fixture | `canonical_fixture_id` | `/fixtures` | état historique de fixture | census fixtures de la compétition-saison |
| Équipe-fixture | `fixture_id + team_id` | dérivé de `/fixtures` | état historique de fixture | deux équipes par fixture applicable |
| Composition | `fixture_id + team_id` | `/fixtures/lineups` | reconstruit post-match | deux compositions si `coverage.lineups=true` |
| Joueur de composition | `fixture_id + team_id + player_id + role` | `/fixtures/lineups` | reconstruit post-match | slots de composition admissibles |
| Formation | `fixture_id + team_id` | `/fixtures/lineups` | reconstruit post-match | compositions admissibles |
| Statistique équipe | `fixture_id + team_id + metric` | `/fixtures/statistics` | post-match | équipes-fixtures admissibles |
| Statistique joueur-match | `fixture_id + team_id + player_id` | `/fixtures/players` | post-match | fixtures couvertes ; lignes joueur publiées séparément |
| Profil joueur-saison | `competition + season + player_id` | `/players` | agrégat de saison | pages attendues selon `paging.total` |
| Événement | `provider_event_identity` | `/fixtures/events` | post-match | fixtures admissibles, vides valides inclus |
| Indisponibilité | clé naturelle joueur-équipe-fixture-raison-période | `/injuries` | observation historique | pagination complète des absences |
| Classement | `competition + season + team_id` | `/standings` | agrégat final de saison | équipes distinctes du census fixtures |
| Journée | `competition + season + round` | `/fixtures/rounds` | calendrier historique | journées distinctes du census fixtures |
| Arbitre-fixture | `fixture_id + normalized_referee` | `/fixtures` | état historique | une affectation par fixture terminale |
| Stade-fixture | `fixture_id + normalized_venue` | `/fixtures` | état historique | une affectation par fixture non annulée |

Le JSON complète cette table avec la politique de null, la politique de
doublon et les usages autorisés pour chaque grain, puis lie chacune des seize
familles P0 à un seul grain canonique.

## Politiques fail-closed

- Une identité manquante ou un doublon contradictoire bloque la fermeture.
- Un doublon exact est neutralisé et ne gonfle jamais le numérateur.
- Un vide acquitté ferme un scope mais n'invente pas de contenu.
- Les métriques équipe ne servent pas de dénominateur principal : le grain
  principal reste l'équipe-fixture.
- Les pages joueurs publient séparément `pages_expected`,
  `pages_received`, `empty_valid_pages` et `paging.total`.
- Les statistiques joueurs publient séparément les fixtures couvertes et les
  joueurs-fixtures matérialisés.
- Les classements finaux ne sont jamais présentés comme point-in-time.

## Blessures et suspensions

`injuries` et `suspensions` partagent `/injuries`, mais sont deux
partitions exclusives d'un même scope complet :

```text
INJURY + SUSPENSION + UNCLASSIFIABLE = source records distincts
```

Une raison non reconnue reste `UNCLASSIFIABLE` et produit
`OPEN_CLASSIFICATION_AMBIGUOUS`. Un zéro suspension n'est
`EMPTY_VALID` qu'après pagination complète et classification intégrale.

## Niveaux de preuve

| Niveau | Pack | Autorité actuelle |
|---|---|---|
| E0 | Golden Synthetic Pack | définitions seulement |
| E1 | exactement 10 fixtures P0 | non matérialisé |
| E2 | exactement 50 fixtures P0 | non matérialisé |
| E3 | une compétition-saison complète | décision requise |
| E4 | P0 complet | `SCALE_APPROVED` requis |

Aucun scan général n'est autorisé avant E3. Dans la présente PR, E0 ne ferme
aucune cellule réelle.
