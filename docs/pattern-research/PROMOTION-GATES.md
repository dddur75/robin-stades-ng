# Gates de promotion des patterns

Version : `pattern-promotion-gates-v1`

## Progression

```text
DISCOVERED
→ HISTORICAL_CANDIDATE
→ EXPOSED_OOS_SURVIVOR
→ EXTERNAL_LEAGUE_SURVIVOR
→ LIVE_SHADOW_CANDIDATE
→ LIVE_SHADOW
→ PUBLIC_TEST
→ VALIDATED
```

Chaque flèche est conditionnelle. `REJECTED`, `LEAKAGE_REJECTED`,
`INSUFFICIENT_SUPPORT`, `DUPLICATE`, `DOMINATED` et `UNSTABLE` sont des sorties
conservées, jamais effacées.

## Gate historique

Pour devenir `HISTORICAL_CANDIDATE`, une règle doit satisfaire simultanément :

- au moins 80 paris sur au moins 3 saisons ;
- ROI à mise fixe strictement positif ;
- q-value ≤ 0,05 après FDR ;
- borne basse du bootstrap groupé strictement positive ;
- aucune fuite ni performance suspectement parfaite ;
- règle canonique non dominée ;
- cote historique réellement observée.

## Gate walk-forward et ligues

`EXPOSED_OOS_SURVIVOR` exige des folds strictement temporels, au moins 15 paris
par fold admissible, au moins deux folds, au moins 67 % de folds positifs et un
dernier fold positif. L’étiquette reste `EXPOSED_HISTORICAL_OOS`.

`EXTERNAL_LEAGUE_SURVIVOR` exige séparément au moins 40 paris et un ROI positif
en Bundesliga et en Serie A, périmètre défini avant le run. Ce test ne
transforme pas une ligue historique déjà examinée en holdout vierge.

## Gate live shadow

Un `LIVE_SHADOW_CANDIDATE` exige en plus :

- feature et prix observables au cutoff live exact ;
- même définition de marché et même règle de règlement ;
- données disponibles dans le pipeline prospectif ;
- aucune concentration non mesurée ;
- protocole shadow préenregistré ;
- décision gelable avant kickoff.

Le corpus actuel porte `SOURCE_PRICE_CLASS_ONLY`. Le gate live demeure donc
fermé, même si un pattern survit aux tests historiques.

La concentration équipe et la sensibilité bookmaker doivent être présentes
dans le rapport avant toute promotion. Elles restent à compléter dans le
dataset marché moyen actuel ; le gate échoue donc fermé si elles manquent.

## Gate `VALIDATED`

Seule une expérience `LIVE_PROSPECTIVE` indépendante peut produire
`VALIDATED`. La durée, le support et les seuils de cette expérience devront
être gelés dans un protocole ultérieur avant sa première décision. Aucun
résultat du Jalon 10 obtenu uniquement sur 2020–2025 ne peut recevoir ce statut.

## Défauts bloquants

Un gate manquant échoue fermé. L’absence de candidat est publiée comme résultat
scientifique, sans assouplir les seuils après coup et sans consommer une
nouvelle source.

Les invariants restent `PRODUCTION_LOCKED`, `REAL_BETS=false`,
`NO_BET_DEFAULT=true` et `SOCIAL_PUBLISHING_ENABLED=false`.
