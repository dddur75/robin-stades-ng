# Prequential Learning Factory V1

## Finalité et portée

La factory prépare l’évaluation et l’apprentissage progressif des cinq
championnats actifs, sans attendre le premier résultat réel. Elle prend en
charge uniquement les marchés `1X2` et `OVER_UNDER_2_5`, aux cutoffs `H-2` et
`NEAR_KICKOFF`.

Le flux canonique est :

```text
données admissibles avant cutoff
→ feature snapshot immuable
→ prédiction immuable
→ kickoff
→ résultat final vérifié
→ règlement et scores
→ éligibilité à un entraînement futur
→ challenger versionné
```

Une exécution synthétique ou un replay historique valide la mécanique, mais ne
constitue jamais une preuve prospective réelle.

## Architecture et stockage

La factory sépare trois responsabilités :

- R2 conserve les manifests, snapshots et artifacts nécessaires au replay ;
- PostgreSQL indexe les versions, prédictions, règlements, scores, métriques,
  entraînements et événements ;
- Git conserve le code, les contrats et des rapports compacts, jamais un gros
  dataset, un modèle binaire ou un payload fournisseur brut.

Les écritures métier sont append-only. Une correction crée une nouvelle version
liée à l’ancienne ; elle ne réécrit pas un snapshot, une prédiction, un résultat
ou une version de modèle déjà enregistré. Chaque événement du ledger porte le
hash de l’événement précédent.

## Temporalité et anti-fuite

Une valeur de feature doit porter sa provenance, son `observed_at`, son cutoff,
sa qualité, sa disponibilité et sa missingness. Une famille bloquée reste
manquante explicitement : elle n’est jamais remplacée par zéro.

La factory refuse :

- une prédiction produite après son cutoff ;
- une donnée observée après le cutoff de la prédiction ;
- un résultat non final ou antérieur au kickoff ;
- un entraînement contenant la fixture en cours d’évaluation ;
- un entraînement sur une fixture non réglée ;
- une mutation sous une clé d’idempotence existante ;
- une promotion automatique.

Le replay reconstruit l’ordre des snapshots, prédictions, versions, règlements
et métriques sans appel fournisseur.

```text
API_FOOTBALL_CALLS = 0
ODDS_API_CREDITS = 0
```

## Modèles

Les scopes préparés sont :

```text
GLOBAL_FIVE_LEAGUES
LIGUE_1
PREMIER_LEAGUE
LIGA
BUNDESLIGA
SERIE_A
```

La référence initiale est le marché dé-vigué, gelé et versionné. Une référence
active n’est jamais modifiée. Le challenger est distinct et ne consomme que les
familles de features dont le gate est admissible. Un modèle propre à une ligue
reste `INSUFFICIENT_TRAINING_SUPPORT` tant que son support est trop faible.

Le gate de promotion est préparé mais toujours fermé :
`PROMOTION_LOCKED`. Aucun résultat de cette mission ne peut déclarer un modèle
rentable, supérieur ou promu.

## Prévision, règlement et métriques

Une prédiction conserve le modèle, sa version, le snapshot de features, le
snapshot de cotes, les probabilités brutes et de marché, le cutoff, la révision
du code et le hash du payload. Ses statuts sont :

```text
FROZEN
REJECTED_LATE
REJECTED_MISSING_GATE
NO_ODDS_REFERENCE
SETTLED
VOID
```

Le règlement accepte uniquement un résultat final vérifié. Il couvre `1X2` et
Over/Under 2,5, reste idempotent et traite explicitement report, annulation,
abandon, correction, doublon et score manquant. Les métriques sont calculées
par ligue, marché, cutoff, modèle, version et mois : Log Loss, Brier,
calibration, exactitude descriptive, couverture et missingness. Le ROI reste
absent lorsqu’aucune décision shadow n’existe.

Le workflow de règlement ne vérifie que les fixtures échues, non réglées ou
encore dans leur suivi borné de correction, au plus tôt 90 minutes après leur
kickoff. Chaque appel
API-Football est précédé d’un guard immuable R2 et la réponse est stockée avant
projection PostgreSQL. Le budget est borné à 10 appels par run, une tentative
par fixture, cinq tentatives au total espacées de six heures. The Odds API
reste à zéro crédit. Un statut non final est conservé comme observation, jamais
comme résultat réglé. Après un premier règlement, les tentatives restantes
peuvent détecter un score corrigé : un score identique ne produit aucune
nouvelle version, tandis qu’un score différent crée une version `CORRECTED`
liée au règlement précédent.

## Politique d’entraînement

L’évaluation peut suivre chaque match. L’entraînement est borné à une cadence
quotidienne ou hebdomadaire et exige au minimum 30 nouvelles fixtures réglées,
éligibles, provenant d’au moins deux ligues. Sinon, le statut est :

```text
TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT
```

Un entraînement produit un manifest avec bornes temporelles, fixtures, ligues,
features, hash, hyperparamètres, métriques, artifact et nouvelle version du
challenger. La référence reste inchangée.

## Opérations et workflows

La CLI publique est figée :

```text
python scripts/run_prequential_learning_factory.py forecast
python scripts/run_prequential_learning_factory.py settle
python scripts/run_prequential_learning_factory.py train
python scripts/run_prequential_learning_factory.py replay
python scripts/run_prequential_learning_factory.py status
```

Le pilote mécanique local utilise une commande séparée et des fixtures
explicitement synthétiques :

```text
python scripts/run_prequential_learning_factory.py pilot --synthetic
```

Les workflows `prequential-prediction.yml`,
`prequential-settlement.yml` et `prequential-training.yml` utilisent tous
`prospective-deep-state` avec `cancel-in-progress: false`. Ils sérialisent ainsi
leurs écritures avec les captures prospectives. Le replay et l’entraînement
n’exposent aucune clé fournisseur et imposent des budgets fournisseur à zéro.

## Robin Experience

La section « Apprentissage en direct » expose les prédictions gelées, modèles,
versions, prochains cutoffs, fixtures réglées, support d’entraînement,
comparaison référence/challenger, résultats par ligue et verrou de promotion.

La Vue essentielle rappelle :

> Robin apprend uniquement après les matchs, sans modifier les prédictions déjà
> publiées.

La Vue expert ajoute hashes, versions, cutoffs, features, métriques, manifests
et événements du ledger. Les fixtures synthétiques et replays historiques sont
identifiés comme tels et ne sont jamais présentés comme des résultats réels.
La commande `status` produit aussi `status.json`, dont le schéma compact est
consommé par le générateur du cockpit. Lors d’une reconstruction depuis un
artifact opérationnel, fournir son chemin avec
`PREQUENTIAL_LEARNING_STATUS`; à défaut, le rapport compact versionné dans Git
conserve honnêtement l’état réel vide.

## Validation et sécurité

La preuve minimale couvre les deux cutoffs, les deux marchés, les cinq ligues,
le rejet tardif, l’immutabilité, le résultat non final, le règlement et replay
idempotents, l’anti-fuite, l’entraînement différé, le changement de version, la
référence inchangée et l’absence de promotion. Les contrôles Python, migration,
YAML/JSON, sécurité, frontend, TypeScript, ESLint et Playwright restent
obligatoires.

Les invariants sont :

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

Le verdict est exactement l’un de :

```text
PREQUENTIAL_LEARNING_FACTORY_READY
PREQUENTIAL_LEARNING_FACTORY_PARTIAL
PREQUENTIAL_LEARNING_FACTORY_FAILED
```

`READY` signifie uniquement que l’infrastructure attend les premiers cutoffs et
résultats réels. Il ne signifie ni rentabilité, ni supériorité du challenger,
ni validation de stratégie, ni autorisation de promotion.
