# Jalon 11 — Deep Football Feature Factory et Matchup Arena

Date de preuve : 27 juillet 2026
Branche : `codex/jalon-11-deep-football-matchups`
Base intégrée : `6bfa906d6ea69183a9d2ce251ddffd0d9bda5c17`
Révision du run autoritatif : `bff3c672c279a94ed97e5a7de0ce0d9b9c56883e`

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

- source historique auditée : commit
  `8f59b5c985b705d1434b4b6a85061b535efcbb0d` ;
- PostgreSQL : dernière preuve préflight à la révision 0007 ; la révision 0008
  reste uniquement la cible Jalon 11 jusqu'à son exécution live vérifiée ;
- R2 : 822 / 822 objets vérifiés, lag 0, 920 725 165 octets attendus ;
- état historique local : 939 552 887 octets ;
- stockage : `STORAGE_PAUSED`, seuil de pause 900 000 000 octets ;
- suppression R2 : 0 ;
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

Test principal préenregistré :

| Modèle | Log Loss | Brier | Conclusion |
|---|---:|---:|---|
| `B0_MARKET_RECALIBRATED_TRAIN_ONLY` | 0,968936 | 0,192127 | référence |
| `B1_MARKET_PLUS_TEAM_REGULARIZED_MULTINOMIAL` | 0,970638 | 0,192468 | aucun gain |

Le delta B1 − B0 vaut `+0,001702211` en Log Loss et `+0,000340731` en
Brier. L'IC bootstrap 95 % du delta Log Loss est
`[-0,000242884 ; +0,003901782]`, p CR1 vaut `0,9638269`, q famille
`0,9638269` et q globale `1,0`. Le test principal ne démontre aucun incrément.

Diagnostics post-contrat non promouvables :

| Diagnostic | Log Loss | Brier | Référence |
|---|---:|---:|---|
| marché brut | 0,966773 | 0,191619 | — |
| team-only multinomiale | 0,988918 | 0,196458 | marché brut |
| team-only gradient boosting | 0,998024 | 0,198176 | marché brut |
| team-only Poisson | 1,046019 | 0,209819 | marché brut |
| team-only Dixon–Coles | 1,046626 | 0,209863 | marché brut |
| marché + équipe, gradient boosting | 0,978452 | 0,193938 | marché recalibré |

Les quatre challengers team-only et le diagnostic incrémental gradient boosting
ont été ajoutés après le contrat principal. Ils servent à la falsification, pas
à la sélection ou à la promotion.

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
  `ff37983cc85ad77716ce1b96e3499da1e29908c133c6b085e86fdfd9667a1cfe` ;
- dataset :
  `2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6` ;
- Parquet :
  `d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673` ;
- tête ledger :
  `8e6d3f0bef494288dca5de747a66b199598c4bdb362024db16d6f8b76aadf5a8` ;
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
principal sans gain contre le marché recalibré, diagnostics post-contrat
clairement étiquetés, familles profondes bloquées, zéro watchlist et zéro
candidat. Aucune donnée démo ne doit apparaître comme live.

Les cinq exports sociaux sont des fichiers statiques pédagogiques. Ils portent
`publishing_enabled=false` et ne sont reliés à aucun réseau.

## Coûts et sécurité

- fournisseur : 0 appel API-Football et 0 crédit The Odds API ;
- pari réel : 0 ;
- collecte P3/P4 : 0 ;
- publication sociale : 0 ;
- données lourdes ajoutées à Git : 0 ;
- suppression et perte : 0.

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
