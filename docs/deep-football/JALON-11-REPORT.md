# Jalon 11 — Deep Football Feature Factory et Matchup Arena

Date de preuve : 27 juillet 2026
Branche : `codex/jalon-11-deep-football-matchups`
Base intégrée : `6bfa906d6ea69183a9d2ce251ddffd0d9bda5c17`
Run autoritatif : `30282406035`
Révision exécutée : `1b74e94d38038b566e14f21ff2c852230cf046fa`
Source historique : `033a98b11b80c059f8986c33c69f1401ce8cf05c`

## Verdict

```text
JALON_11_BLOCKED_BY_DATA_GATES
```

Sous-verdicts :

```text
TEAM_FEATURES_PARTIAL_DESCRIPTIVE_ONLY
PLAYER_FEATURES_BLOCKED
ABSENCE_FEATURES_BLOCKED
LINEUP_FEATURES_BLOCKED
FORMATION_MATCHUPS_BLOCKED
FOOTEDNESS_MATCHUPS_BLOCKED
```

Ce verdict signifie que la fabrique équipe est reproductible pour un diagnostic
rétrospectif, mais que `TEAM_GATE=PARTIAL` et que la preuve profonde
joueurs/matchups ne peut pas être produite honnêtement avec les cutoffs actuels.
Il ne signifie ni échec d'infrastructure, ni stratégie validée.

## Infrastructure et sources

Le snapshot preflight, capturé avant l'exécution, reste une preuve historique :
source `8f59b5c985b705d1434b4b6a85061b535efcbb0d`, PostgreSQL 0007,
822 / 822 objets R2 et 920 725 165 octets attendus. Il n'est ni écrasé ni
présenté comme l'état post-run.

Preuve opérationnelle du run `30282406035` :

- source historique :
  `033a98b11b80c059f8986c33c69f1401ce8cf05c` ;
- PostgreSQL : `0008_jalon11_deep_football` vérifiée en live ;
- PostgreSQL primaire puis replay : 304 preuves examinées, 0 insertion et
  304 doublons évités à chaque passage ;
- fidélité scientifique : six évaluations legacy reconnues comme équivalentes
  numériquement sous `j11-scientific-float15-v1`
  (`legacy_numeric_equivalent_evaluations=6`) ;
- R2 : 25 453 / 25 453 objets vérifiés, un upload de 2 000 155 octets, lag 0 ;
- stockage : `STORAGE_PAUSED`, seuil de pause 900 000 000 octets ;
- suppression R2 : 0 ;
- mutation source R2 : 0 ;
- appels API-Football : 0 ;
- crédits The Odds API : 0.

## Couverture

Le marché et les features équipe couvrent 10 732 fixtures de cinq ligues sur
2020–2025. La profondeur joueurs/lineups n'existe qu'en Ligue 1 :

- 4 134 lignes équipes-joueurs ;
- 4 138 lignes équipes-lineups et XI exacts ;
- 4 127 formations/grilles complètes ;
- 12 801 blessures non point-in-time ;
- 0 pied fort sourcé.

Les lineups et données joueurs sont `POST_MATCH_ONLY`. Un contenu complet ne
prouve pas qu'il était disponible avant kickoff.

## Dataset

`TEAM_PREMATCH` contient 10 732 lignes, sans doublon ni attrition du périmètre
marché. Son hash logique est
`2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6`.
Le Parquet lourd pèse 2 000 155 octets, son SHA-256 est
`d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673`,
et il reste hors Git.

La cible est exclue des agrégats par ordre de mise à jour algorithmique, mais
les 10 732 frontières de feature sont égales au kickoff et aucun
`source_observed_at` ligne par ligne n'est prouvé. `TEAM_GATE` est donc
`PARTIAL` : recherche descriptive permise, promotion et live interdits.

Les datasets `PLAYER_PRELINEUP`, `POST_LINEUP`, `FORMATION_MATCHUP` et
`FOOTEDNESS_MATCHUP` sont bloqués ; aucun substitut simulé n'est présenté comme
observé.

## Modèles

Échantillon apparié d'évaluation : 7 081 fixtures.

Test principal correctif :

| Modèle | Log Loss | Brier | Conclusion |
|---|---:|---:|---|
| `B0_MARKET_RECALIBRATED_TRAIN_ONLY` | 0,968936 | 0,192127 | référence |
| `B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` | 0,970638 | 0,192468 | aucun gain |

Le delta B1 − B0 vaut `+0,001702211` en Log Loss et `+0,000340731` en
Brier. L'IC bootstrap 95 % du delta Log Loss est
`[-0,000242884 ; +0,003901782]`, p CR1 vaut `0,9638269`, q famille
`0,9638269` et q globale `1,0`. Le test principal ne démontre aucun incrément.

Ce test n'est pas préenregistré. Il est défini par
`1.0.0-amendment-1`, amendement correctif enregistré après l'examen des
diagnostics team-only et avant le run autoritatif. Son hash est
`37b41db1912790c2c2efb83600a6b5e3708e84dac61e81aa4e15f73d6af166fa`.
La chronologie de cet amendement et `TEAM_GATE=PARTIAL` interdisent toute
promotion.

Diagnostics post-contrat initial, antérieurs à l'amendement et non
promouvables :

| Diagnostic | Log Loss | Brier | Référence |
|---|---:|---:|---|
| marché brut | 0,966773 | 0,191619 | — |
| team-only multinomiale | 0,988918 | 0,196458 | marché brut |
| team-only gradient boosting | 0,998024 | 0,198176 | marché brut |
| team-only Poisson | 1,046019 | 0,209819 | marché brut |
| team-only Dixon–Coles | 1,046626 | 0,209863 | marché brut |
| marché + équipe, gradient boosting | 0,978452 | 0,193938 | marché recalibré |

Les quatre challengers team-only et le diagnostic incrémental gradient boosting
ont été ajoutés après le contrat initial. Ils ont été examinés avant
l'enregistrement de l'amendement correctif et restent non promouvables. Cette
chronologie est explicitement conservée ; elle n'est pas requalifiée en
préenregistrement.

La campagne 11F est un diagnostic rétrospectif descriptif : cinq rotations,
supports 2 743 à 3 040, zéro direction positive, zéro survivante et
`promotion_eligible=false`.

## Hypothèses et campagnes

11A est exécutée cache-only comme diagnostic descriptif malgré
`TEAM_GATE=PARTIAL`. 11E est terminée comme évaluation de gates, avec H11-001 à
H11-008 toutes `DATA_GATE_BLOCKED`. 11F est exécutée comme diagnostic
descriptif rétrospectif non promouvable. 11B, 11C, 11D et 11G restent
`DATA_GATE_BLOCKED`. Aucun effet brut ou ajusté n'est inventé pour les
hypothèses inéligibles.

Le red-team confirme :

- appariement exact ;
- cible exclue des agrégats, mais preuve temporelle source incomplète ;
- aucun retuning de seuil ;
- aucune prétention causale ;
- contrôles négatifs fail-closed ;
- `impossible_condition` réellement calculé sur 7 081 lignes avec le prédicat
  `OUTCOME_IS_HOME_AND_AWAY`, support 0 et statut
  `EXECUTED_ZERO_SUPPORT_NO_PROMOTION` ;
- aucun signal promouvable.

## Replay et preuve publique

- hash primaire et replay :
  `437efb112c25891692420faafd3364f691f6e0a303e3524470992e9838f63355` ;
- dataset :
  `2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6` ;
- Parquet :
  `d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673` ;
- tête ledger :
  `90bd34d99a689553246ce3b57ea344d751fb1f948cdc048661d6c2e0b22b92a8` ;
- replay complet : hashes campagne, dataset, Parquet et ledger identiques ;
- doublons métier, pertes et mismatches : 0 ;
- ledger V2 : 24 événements, chaîne de hashes vérifiée ;
- watchlist : 0 ;
- candidats : 0 ;
- décisions : 0 ;
- mise : 0 ;
- bankroll shadow : 1 000 unités, inchangée.

## Robin Live et social

Le résultat attendu dans Matchup Lab est un résultat nul explicite : test
principal sans gain contre le marché recalibré, diagnostics antérieurs à
l'amendement clairement étiquetés, familles profondes bloquées, zéro watchlist
et zéro candidat. Aucune donnée démo ne doit apparaître comme live.

Les cinq exports sociaux sont des fichiers statiques pédagogiques. Ils portent
`publishing_enabled=false` et ne sont reliés à aucun réseau.

## Coûts et sécurité

- fournisseur : 0 appel API-Football et 0 crédit The Odds API ;
- pari réel : 0 ;
- collecte P3/P4 : 0 ;
- publication sociale : 0 ;
- données lourdes ajoutées à Git : 0 ;
- suppression et perte : 0 ;
- fenêtre opérationnelle du run GitHub : 1 543 s (25 min 43 s), somme des
  jobs : 1 526 s (25 min 26 s) ;
- upload R2 : 1 objet, 2 000 155 octets.

```text
STORAGE_PAUSED
P3/P4_PAUSED
PRODUCTION_LOCKED
REAL_BETS=false
NO_BET_DEFAULT=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Le champ JSON compact correspondant à `P3/P4_PAUSED` est
`P3_P4_PAUSED=true`.

Aucun secret n'est consigné. La branche ne doit pas être fusionnée
automatiquement.
