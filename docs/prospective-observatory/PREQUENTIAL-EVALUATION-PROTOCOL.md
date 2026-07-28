# Protocole d’évaluation préquentielle

## Séquence immuable

```text
capture
→ feature snapshot
→ PREDICTION_FROZEN
→ décision shadow ou NO_BET
→ résultat
→ MATCH_SETTLED
→ métriques
→ CHALLENGER_TRAINING_ELIGIBLE
→ mise à jour éventuelle du challenger
```

Une prédiction gelée lie fixture, ligue, modèle, rôle, version, features,
cutoff, cote, timestamp et hashes canoniques. Elle ne peut être réécrite.
Un règlement avant kickoff, sans prédiction préalable ou incohérent avec la
fixture est refusé.

## Modèles suivis

Le registre prépare six scopes :

- modèle global cinq ligues ;
- Ligue 1 ;
- Premier League ;
- Liga ;
- Bundesliga ;
- Serie A.

Chaque scope possède une référence `REFERENCE` gelée et peut posséder un
challenger `CHALLENGER`. La référence émet `REFERENCE_UNCHANGED` et ne reçoit
jamais de mise à jour automatique.

## Challenger

`CHALLENGER_UPDATED` n’est autorisé qu’après `MATCH_SETTLED` et
`CHALLENGER_TRAINING_ELIGIBLE`. Chaque mise à jour crée une nouvelle version
liée à la précédente ; elle ne modifie aucune prédiction passée. Le même match
peut devenir une donnée d’entraînement future, mais jamais une preuve
indépendante de la prédiction déjà évaluée sur ce match.

## Anti-fuite

Le registre refuse :

- un résultat dans le feature snapshot ;
- un training avant règlement ;
- une mutation de version ;
- une seconde signification sous la même clé d’idempotence ;
- une promotion automatique.

Le ledger append-only contient exactement les événements
`PREDICTION_FROZEN`, `MATCH_SETTLED`, `CHALLENGER_TRAINING_ELIGIBLE`,
`CHALLENGER_UPDATED` et `REFERENCE_UNCHANGED`. Chaque événement chaîne le hash
précédent. Le replay reconstruit donc le même ordre et les mêmes versions sans
accès fournisseur.

## Statut de cette mission

La mission crée le protocole, les registres et les tests. Elle n’entraîne aucun
modèle sur les nouvelles captures et n’autorise aucune promotion. Les décisions
restent shadow ou `NO_BET`, avec `PRODUCTION_LOCKED` et `REAL_BETS=false`.
