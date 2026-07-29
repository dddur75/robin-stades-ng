# Protocole d’évaluation préquentielle

## Séquence immuable

```text
capture
→ FEATURE_SNAPSHOT_FROZEN
→ PREDICTION_FROZEN
→ décision shadow ou NO_BET
→ résultat final vérifié
→ FIXTURE_SETTLED
→ PREDICTION_SCORED
→ TRAINING_ELIGIBLE
→ entraînement différé ou nouvelle version du challenger
```

Une prédiction gelée lie fixture, ligue, modèle, rôle, version, features,
marché, cutoff, cote, timestamp et hashes canoniques. Elle ne peut être
réécrite. Les cutoffs canoniques sont `H-2` et `NEAR_KICKOFF`; les marchés
admis sont `1X2` et `OVER_UNDER_2_5`.

Une prédiction tardive produit `PREDICTION_REJECTED` avec le statut
`REJECTED_LATE`. Un gate manquant produit `REJECTED_MISSING_GATE`. Un règlement
avant kickoff, sans prédiction préalable, sur un résultat non final ou
incohérent avec la fixture est refusé.

## Modèles suivis

Le registre prépare six scopes :

- modèle global cinq ligues ;
- Ligue 1 ;
- Premier League ;
- Liga ;
- Bundesliga ;
- Serie A.

Chaque scope possède une référence `REFERENCE` gelée, initialement le marché
dé-vigué, et peut posséder un challenger `CHALLENGER`. La référence émet
`REFERENCE_UNCHANGED` et ne reçoit jamais de mise à jour automatique. Un modèle
propre à une ligue peut rester `INSUFFICIENT_TRAINING_SUPPORT`.

## Challenger

`CHALLENGER_TRAINING_STARTED` n’est autorisé qu’après `FIXTURE_SETTLED` et
`TRAINING_ELIGIBLE`. Il faut au moins 30 nouvelles fixtures admissibles dans au
moins deux ligues. Sinon, la factory émet `TRAINING_DEFERRED` avec le statut
`TRAINING_DEFERRED_INSUFFICIENT_NEW_SUPPORT`.

Chaque entraînement crée un manifest borné dans le temps puis une nouvelle
version via `CHALLENGER_VERSION_CREATED`. Il ne modifie aucune prédiction
passée. Le même match peut devenir une donnée d’entraînement future, mais jamais
une preuve indépendante de la prédiction déjà évaluée sur ce match.

## Anti-fuite

Le registre refuse :

- un résultat dans le feature snapshot ;
- une observation reçue après le cutoff ;
- un training avant règlement ;
- une mutation de version ;
- une seconde signification sous la même clé d’idempotence ;
- une promotion automatique.

Le ledger append-only contient les événements :

```text
FEATURE_SNAPSHOT_FROZEN
PREDICTION_FROZEN
PREDICTION_REJECTED
FIXTURE_SETTLED
PREDICTION_SCORED
TRAINING_ELIGIBLE
TRAINING_DEFERRED
CHALLENGER_TRAINING_STARTED
CHALLENGER_VERSION_CREATED
REFERENCE_UNCHANGED
PROMOTION_BLOCKED
```

Chaque événement chaîne le hash précédent. Le replay reconstruit donc le même
ordre, les mêmes versions, règlements et métriques sans accès fournisseur.

## Révisions et corrections

Les snapshots, prédictions et événements sont append-only. Une correction de
résultat crée une version liée à la précédente et recalcule les scores sans
effacer la preuve originale. Les rencontres reportées, annulées, abandonnées,
dupliquées ou sans score restent non réglées ou deviennent `VOID` selon le
contrat de règlement ; aucune rencontre n’est réglée sur un statut non final.

## Métriques

La Log Loss, le score de Brier, la calibration, l’exactitude descriptive, la
couverture et la missingness sont séparés par ligue, marché, cutoff, modèle,
version et mois. La comparaison référence/challenger reste descriptive tant que
le support prospectif est insuffisant. Aucun ROI n’est affiché sans décision
shadow réglée.

## Statut de cette mission

La mission crée la factory, ses registres, workflows, replay et tests. Elle
n’entraîne aucun modèle réel tant que le support n’est pas admissible et
n’autorise aucune promotion. Les décisions restent shadow ou `NO_BET`, avec
`PRODUCTION_LOCKED`, `REAL_BETS=false` et `PROMOTION_LOCKED`.

Le verdict `PREQUENTIAL_LEARNING_FACTORY_READY` signifie que l’infrastructure
attend les premiers cutoffs et résultats réels. Il ne signifie ni rentabilité,
ni supériorité du challenger, ni stratégie validée.

Le contrat opérationnel complet est documenté dans
`docs/prequential-learning/PREQUENTIAL-LEARNING-FACTORY-V1.md`.
