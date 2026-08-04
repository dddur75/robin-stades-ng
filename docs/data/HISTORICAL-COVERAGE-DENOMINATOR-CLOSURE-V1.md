# Historical Coverage Denominator Closure V1

## Verdict

`COVERAGE_DENOMINATOR_CLOSURE_PARTIAL`

La définition du périmètre P0 est fermée à E0, mais sa preuve empirique reste
ouverte. Les 480 cellules sont `OPEN_NOT_EVALUATED`. Cette branche n'autorise
aucun appel fournisseur, replay général, achat, écriture R2, promotion ou
montée en charge.

## Deux périmètres étanches

- `P0_2020_2025` : cinq compétitions, saisons 2020 à 2025 et seize familles.
  Il forme la seule base des gates.
- `EXTENDED_ALL_AVAILABLE` : observations anciennes, futures, hors grille ou
  explicitement partielles. Elles restent visibles sans pénaliser P0.

La grille autoritative est le produit cartésien :

```text
5 compétitions × 6 saisons × 16 familles = 480 cellules
```

Elle contient exactement 96 cellules par compétition, 80 par saison et 30 par
famille, dont 30 cellules `suspensions`. Une observation absente ne supprime
jamais sa cellule. Une observation partielle dans les dimensions P0 est
classée dans `EXTENDED_ALL_AVAILABLE` et n'alimente pas un gate.

Le contrat Historical Deep amont est vérifié par hash canonique et hash de
fichier UTF-8/LF. Le catalogue de grains autoritatif est
`configs/data/football-grain-catalog-v1.json`; chaque `definition_hash`
inclut sa règle et sa clé distincte.

## Contrat d'une ligne de couverture

Chaque cellule du registre publie exactement les dimensions et preuves
suivantes :

```text
scope
competition
season
family
grain
distinct_key
advertised_coverage
expected_count
received_count
empty_valid_count
invalid_count
coverage_percent
null_rate
source_endpoint
payload_hash
receipt_hash
temporal_class
gate
gate_reason
```

Dans cette PR, les nombres empiriques et hashes par cellule restent `null`.
Leur absence signifie « non prouvé », jamais zéro. Le manifeste PR26 comporte
1 067 cellules observées, mais aucune n'a de preuve census ; cette union n'est
donc jamais projetée artificiellement dans la grille P0.

## Trois taux séparés

Chaque cellule porte trois triplets indépendants :

1. `scope_completion` : scopes complets ou vides valides sur scopes attendus ;
2. `normalization_integrity` : entités uniques normalisées sur entités brutes
   admissibles ;
3. `content_presence` : slots de contenu présents sur slots attendus.

`coverage_rate` et `overall_rate` sont interdits. Un dénominateur inconnu
reste `UNKNOWN` avec numérateur, dénominateur et valeur nuls. Un scope
intégralement prouvé vide utilise `EMPTY_VALID` et ne crée aucun contenu.

Les agrégations sont pondérées par les dénominateurs :

```text
sum(numerators) / sum(known denominators)
```

Un seul taux applicable `UNKNOWN` rend l'agrégat `UNKNOWN` ; il n'est pas
silencieusement exclu. Deux dénominateurs inégaux sont testés afin d'empêcher
une moyenne simple des pourcentages.

## Census R2-first réutilisé

`coverage-census-manifest-v1` possède une identité stable liée au scope,
à la grille et au contrat, indépendamment d'un run GitHub. Il référence sans
les recopier les preuves PR26 :

- 2 321 payloads rejoués et 2 321 receipts vérifiés ;
- 2 023 144 lignes normalisées ;
- zéro mismatch de hash ;
- 1 067 cellules dans l'union observée ;
- zéro cellule avec dénominateur census.

La recherche logique suit payloads de ligues, fixtures, manifests census,
receipts, intentions, flags et inventories. La présente phase effectue zéro
lecture/écriture R2 et zéro replay. Les appels fournisseur restent interdits ;
le plafond conditionnel de 100 appels census n'est pas autorisé.

## Applicabilité et absences

- `FT`, `AET`, `PEN` : familles post-match applicables ;
- `PST`, `CANC`, `NS`, `TBD` : non applicables ;
- `ABD`, `INT`, `SUSP` et états inconnus : bloquants sans règle
  versionnée.

`injuries` et `suspensions` partagent `/injuries`, mais sont des
partitions exclusives. Un texte non reconnu, par exemple « Personal reasons »,
reste `UNCLASSIFIABLE` et produit
`OPEN_CLASSIFICATION_AMBIGUOUS` :

```text
INJURY + SUSPENSION + UNCLASSIFIABLE = source records distincts
```

La position de page est exclue de la clé naturelle. Un doublon exact est
neutralisé ; un conflit produit `OPEN_CONFLICTING_DUPLICATE`. Un zéro
suspension ne devient `EMPTY_VALID` qu'après pagination et classification
intégrales.

## Niveaux E0–E4

| Niveau | Pack | État | Pouvoir de fermeture |
|---|---|---|---|
| E0 | Golden Synthetic Pack, moins de 100 entités | `PASS_DEFINITION_ONLY` | aucune cellule réelle |
| E1 | exactement 10 fixtures P0 | non matérialisé | aucun |
| E2 | exactement 50 fixtures P0 | non matérialisé | aucun |
| E3 | une compétition-saison complète | décision requise | cellules du scope autorisé |
| E4 | P0 complet | `SCALE_APPROVED` requis | P0 uniquement |

Aucun scan général n'est permis avant E3. Une fermeture réelle exige E3 ou
E4, une autorisation de niveau, les comptes, les taux complets ou vides
valides et les hashes de lignée. Deux échecs similaires imposent
`REDESIGN_REQUIRED` ; la troisième tentative identique est interdite.

## Gates et propriétés

Les huit gates fonctionnels recalculés restent
`BLOCKED_BY_COVERAGE` :

- `TEAM_GATE`, `PLAYER_GATE`, `PLAYER_FORM_GATE` ;
- `LINEUP_GATE`, `FORMATION_GATE`, `STARTER_BASELINE_GATE` ;
- `DISCIPLINE_GATE`, `ABSENCE_GATE`.

`WEATHER_GATE` et `FOOTEDNESS_GATE` restent
`BLOCKED_BY_SOURCE`, sans bloquer le verdict de couverture API-Football.
Les huit verdicts de pipeline, replay, couverture, features, backtest et
sources sont publiés séparément avec leurs références de preuve.

Le catalogue `CALENDAR_FATIGUE` est réconcilié avec les 17 propriétés
canoniques, dont `matches_5d` et `matches_10d`. L'état actuel est 0/17 :
aucune famille ni propriété n'est débloquée. L'hypergraphe reste
`NOT_OPENED_DATA_GATES_INSUFFICIENT`.

## Artefacts

- `configs/data/football-grain-catalog-v1.json` et son document ;
- `reports/coverage/p0-denominator-grid-v1.json` : 480 lignes ;
- `reports/coverage/e0-denominator-proof-v1.json` : Golden Pack ;
- `reports/coverage/coverage-census-manifest-v1.json` : lignée R2-first ;
- `reports/coverage/p0-readiness-gates-v1.json` : gates et verdicts ;
- `reports/coverage/p0-property-readiness-v1.json` : familles/propriétés ;
- `reports/coverage/denominator-closure-summary-v1.json` : verdict global ;
- `cockpit/private-coverage/p0-denominator-status-v1.json` : projection
  privée sanitisée.

Les sept artefacts générés possèdent un `proof_hash` canonique et valident
le JSON Schema 2020-12. La projection privée conserve les colonnes de
compréhension, mais remplace `source_endpoint` par
`SANITIZED_IN_PRIVATE_PROJECTION`, garde les hashes absents à `null` et ne
contient ni payload brut, clé R2, secret, ni endpoint fournisseur.

GitHub Pages publie automatiquement `/docs` après merge sur `main`. Ce
document ne contient donc aucune donnée privée. La PR demeure brouillon et
non fusionnée.
