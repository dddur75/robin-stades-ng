# Universal Football Hypothesis Genome V2

## Objet

Le Genome V2 transforme la Factory V1 en univers symbolique, typé, paresseux,
déterministe, checkpointé et rejouable. Les huit propositions H11 de David
restent des exemples `OWNER_PROPOSED`; elles ne bornent jamais l'univers.

Le verdict interne :

```text
HYPOTHESIS_UNIVERSE_SYMBOLICALLY_COMPLETE
```

signifie uniquement que la grammaire est fermée sur le catalogue versionné
`FOOTBALL_PROPERTY_UNIVERSE_V1`. Il ne prétend pas démontrer que toutes les
idées football concevables ont été énumérées. Avec une profondeur scientifique
non bornée, l'univers théorique est `COUNTABLY_INFINITE`.

## Passes d'idéation

Les audits ont été menés séparément par les rôles suivants :

1. analyste tactique, scout, entraîneur, préparateur physique et médecin ;
2. météorologue, spécialiste stades/pelouses, logistique, arbitrage et
   discipline ;
3. statisticien, spécialiste marchés, ingénieur data, red-team scientifique
   et agent d'idéation IA.

### Passe 1 — tactique

Ajouts structurants : structures avec/sans ballon, relance, pressing,
rest-defence, occupation des couloirs et demi-espaces, rôles, substitutions,
coups de pied arrêtés et tactique dynamique.

Question de fin de passe :

> Quelles familles, entités, relations ou interactions football ne sont
> toujours pas représentées ?

Réponse : profils joueurs, opposition directe, banc, décisions du staff,
charge et santé.

### Passe 2 — joueurs, staff et santé

Ajouts : pied sourcé, rôles par phase, unités tactiques, réseaux, remplaçabilité,
microcycles, charge, retour de blessure, restrictions de minutes et
gouvernance des données médicales.

Question de fin de passe : identique.

Réponse : environnement, trajets réels, officiels, information et
microstructure de marché.

### Passe 3 — environnement et logistique

Ajouts : stade versionné, surface, terrain, prévision météo au cutoff distincte
de l'observation réelle, déplacement planifié/réel, arrivée, fuseaux,
récupération, arbitres assistants et VAR.

Question de fin de passe : identique.

Réponse : contexte simultané de compétition, régimes fournisseurs,
causalité et méta-qualité.

### Passe 4 — science, marché et red-team

Ajouts : validation enfant-parent appariée, baseline et marché, log-loss,
Brier, complexité, concentration, gatekeeping hiérarchique, cibles
non-marché, liquidité, dispersion, règlements et changements de schéma.

Question de fin de passe : identique.

Réponse : aucune famille structurante majeure supplémentaire; les ajouts
restants détaillent des sous-familles déjà représentées.

### Passe 5 — fermeture

La dernière passe a contrôlé les exemples du prompt et les angles morts des
passes précédentes. Elle a ajouté les propriétés manquantes au registre ou les
a explicitement placées derrière un `DATA_GATE_BLOCKED`. Cette règle d'arrêt
est documentée; ce n'est pas une preuve mathématique d'exhaustivité.

## Ontologie

Le registre contient 486 propriétés explicites réparties dans 28 familles,
dont la météo est native. Chaque définition contient les champs demandés par
le contrat, plus :

- rôle scientifique ;
- statut de disponibilité et raison de blocage ;
- type d'observation et dimension physique ;
- hash de schéma source ;
- champs temporels `event_time`, `published_at`, `provider_updated_at`,
  `observed_at`, `ingested_at`, `valid_from` et `valid_to`.

Les 48 champs effectivement consommés par les schémas versionnés Robin,
Football-Data et API-Football sont classés. Le résultat
`unclassified_source_fields = 0` s'applique strictement à cet inventaire
versionné. Les payloads fournisseur opaques non inventoriés ne sont pas
présentés comme exhaustivement classés.

## Grammaire

Une expression combine :

```text
ENTITY_SCOPE
× CONTEXT
× PREDICATE_1..N
× RELATION
× TEMPORAL_WINDOW
× CUTOFF
× TARGET
× OPTIONAL_MARKET
× OPTIONAL_PRICE_CONTRACT
× OPTIONAL_GRAPH_PATTERN
```

La profondeur scientifique n'est pas limitée. Le budget d'une campagne fixe
une profondeur technique et une frontière de reprise sans redéfinir l'univers.

La canonicalisation trie les conjonctions commutatives, normalise les
ensembles et sépare l'empreinte sémantique de la provenance. Une règle de
profondeur trois possède trois parents immédiats : le modèle logique est donc
un DAG. `parent_node_id` reste une projection UI déterministe, tandis que
`parent_ids` conserve toutes les dérivations immédiates.

## Moteurs

Les versions fonctionnelles et déterministes comprennent :

- énumération typée ;
- Apriori avec pruning anti-monotone ;
- beam search support/qualité/complexité, sans score ROI isolé ;
- subgroup discovery par WRAcc ;
- chemins de règles avec seuils train-only ;
- régression symbolique pénalisée par complexité ;
- programmation génétique seedée ;
- MCTS avec UCB ;
- residual mining face à une baseline ;
- temporal motif mining ;
- graph pattern mining ;
- compilateur IA vers AST typé.

Le compilateur IA ne produit aucun support, aucune métrique et aucune
promotion.

## Pruning et statuts

Deux axes sont séparés :

- disposition de matérialisation : exécuté, bloqué, pruné, différé ou longue
  traîne ;
- statut scientifique : non testé, signal exploratoire, rejeté, gelé ou
  validé.

`COMPUTE_DEFERRED` ne constitue jamais un rejet scientifique.

## Validation

La validation compare chaque enfant à ses parents sur les mêmes observations,
à une baseline et au marché déviggué. Les transformations et seuils appris
sont calculés uniquement sur le train. Les contrôles prévus incluent :

- rolling-origin imbriqué ;
- log-loss et Brier primaires ;
- ROI secondaire uniquement avec prix reproductible ;
- coût de complexité et perte de support ;
- stabilité et concentration ;
- bootstrap groupé et permutations préservant temps/ligue/équipes ;
- leave-one-team/season/league comme diagnostics ;
- gatekeeping hiérarchique et corrections par campagne.

Aucun moteur ne peut produire automatiquement `VALIDATED`.

## Pilote cache-only

Le pilote s'appuie uniquement sur les preuves déjà présentes :

- 36 423 matchs legacy, dont la provenance brute est absente ;
- 10 732 lignes cinq ligues ;
- 7 081 lignes d'évaluation équipe/marché ;
- 11 variables équipe/calendrier ;
- zéro frontière matérielle strictement antérieure au kickoff dans J11.

Le diagnostic équipe + marché n'améliore pas le marché recalibré :
delta log-loss `+0,001702`, `q=1`. Il n'existe donc aucune stratégie validée.

Le pilote publie génération, matérialisation, exécution, pruning, blocages,
calcul différé, longue traîne, profondeur, temps, heap Python, checkpoint et
replay. Le temps et la mémoire ne participent pas au hash du replay.

## Stockage et sécurité

```text
PostgreSQL → propriétés, campagnes, nœuds et arêtes indexables append-only
R2         → preuves et exports lourds
Git        → code, migrations, contrats, index compacts, hashes, classements
Build      → pages détaillées bornées
```

Les 14 pages contenant les 700 règles J10 ont été retirées de Git. Le
générateur continue à produire ces pages dans `artifacts/`, répertoire ignoré.

Les verrous restent :

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
PROMOTION_LOCKED
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```
