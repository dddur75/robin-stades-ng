# P0 E2 Capability Sample V1

## Verdict

`PASS_AND_HOLD`

E2 a mesuré neuf capacités sur exactement 100 fixtures réelles de saison 2024,
sans promouvoir de capacité en `READY_STRICT` ou `READY_RECONSTRUCTED`. Sept
capacités sont candidates E3A. `PLAYER_STATISTICS` nécessite un correctif ciblé
de grain/identité et `CALENDAR` un contrat de temporalité connu-à-la-date.

E3A et les masques n'ont pas été exécutés.

## Autorités

- Sélection : `reports/evidence/e2/e2-selection-manifest-v1.json`
- Mesure : `reports/evidence/e2/e2-measurement-v1.json`
- Matrice : `reports/evidence/e2/e2-capability-matrix-v1.json`
- Comparaison E1B/E2 : `reports/evidence/e2/e1b-e2-comparison-v1.json`
- Candidats E3A : `reports/evidence/e2/e2-e3a-candidate-set-v1.json`
- Coûts : `reports/evidence/e2/e2-costs-v1.json`
- Replay : `reports/evidence/e2/e2-replay-verification-v1.json`
- Dashboard, données seulement : `reports/evidence/e2/e2-dashboard-contract-v1.json`

Le manifeste de sélection est le seul fichier qui énumère les 100 fixtures.
Aucun payload fournisseur brut ni reçu brut complet n'est suivi dans Git.

## Sélection gelée

| Ligue | Fixtures | Ancres E1B | Nouvelles | Équipes | Période UTC |
|---|---:|---:|---:|---:|---|
| Premier League | 20 | 2 | 18 | 20 | 2024-08-24 – 2025-05-20 |
| Ligue 1 | 20 | 2 | 18 | 19 | 2024-08-18 – 2025-05-21 |
| Bundesliga | 20 | 2 | 18 | 19 | 2024-08-25 – 2025-05-26 |
| Serie A | 20 | 2 | 18 | 20 | 2024-08-24 – 2025-05-18 |
| Liga | 20 | 2 | 18 | 20 | 2024-08-23 – 2025-05-18 |

Chaque ligue conserve ses deux ancres exactes et ajoute une fixture déterministe
dans chacune de 18 strates temporelles. Les 100 fixtures sont uniques et leurs
clés payload/reçu ainsi que leurs hashes sont épinglés à l'inventaire signé.

```text
selection_hash = 5f0ad80ce5ae43b4b4010c0e06dff8828330bcd60282bf940c9f1e87e601286b
anchor_hash = 045d98f29f99aedffe42f8a03547cd78d2d01254505cb86aa2070d97db51dca2
new_fixture_hash = c3525650a1eec557213b402bc0ddeae9b80cc150289804a345df01033c0a474c
```

La génération locale a été répétée deux fois avec un résultat byte-identique.
DP6, C2 et DP5 ont rendu `E2_SELECTION_READY` avant la lecture R2.

## Mesures par ligue

Notation : `E/R/V/U/I` = expected / received / empty-valid / unknown / invalid.
`—` signifie que la capacité est événementielle et ne possède pas de nombre
attendu inventé ; le volume et l'intégrité sont mesurés, pas un taux de couverture.

| Ligue | Capacité | E/R/V/U/I | Couverture | Statut E2 |
|---|---|---|---:|---|
| Premier League | TEAM | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Premier League | PLAYER | 800/800/0/0/0 | 100 % | E2_MEASURED |
| Premier League | LINEUP | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Premier League | FORMATION | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Premier League | EVENTS | —/324/0/0/0 | — | E2_MEASURED |
| Premier League | TEAM_STATISTICS | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Premier League | PLAYER_STATISTICS | 800/800/0/0/0 | 100 % | E2_MEASURED |
| Premier League | DISCIPLINE_GENERIC | —/81/1/0/0 | — | E2_MEASURED |
| Premier League | CALENDAR | 20/20/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | TEAM | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | PLAYER | 800/800/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | LINEUP | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | FORMATION | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | EVENTS | —/303/0/0/0 | — | E2_MEASURED |
| Ligue 1 | TEAM_STATISTICS | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | PLAYER_STATISTICS | 800/800/0/0/0 | 100 % | E2_MEASURED |
| Ligue 1 | DISCIPLINE_GENERIC | —/72/2/0/0 | — | E2_MEASURED |
| Ligue 1 | CALENDAR | 20/20/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | TEAM | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | PLAYER | 796/796/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | LINEUP | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | FORMATION | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | EVENTS | —/356/0/0/0 | — | E2_MEASURED |
| Bundesliga | TEAM_STATISTICS | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | PLAYER_STATISTICS | 796/796/0/0/0 | 100 % | E2_MEASURED |
| Bundesliga | DISCIPLINE_GENERIC | —/83/0/0/0 | — | E2_MEASURED |
| Bundesliga | CALENDAR | 20/20/0/0/0 | 100 % | E2_MEASURED |
| Serie A | TEAM | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Serie A | PLAYER | 923/923/0/0/0 | 100 % | E2_MEASURED |
| Serie A | LINEUP | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Serie A | FORMATION | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Serie A | EVENTS | —/331/0/0/0 | — | E2_MEASURED |
| Serie A | TEAM_STATISTICS | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Serie A | PLAYER_STATISTICS | 923/923/0/0/0 | 100 % | E2_MEASURED |
| Serie A | DISCIPLINE_GENERIC | —/87/0/0/0 | — | E2_MEASURED |
| Serie A | CALENDAR | 20/20/0/0/0 | 100 % | E2_MEASURED |
| Liga | TEAM | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Liga | PLAYER | 890/890/0/0/0 | 100 % | E2_MEASURED |
| Liga | LINEUP | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Liga | FORMATION | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Liga | EVENTS | —/325/0/0/0 | — | E2_MEASURED |
| Liga | TEAM_STATISTICS | 40/40/0/0/0 | 100 % | E2_MEASURED |
| Liga | PLAYER_STATISTICS | 890/889/0/1/1 | 99,88764 % | E2_MEASURED_PARTIAL |
| Liga | DISCIPLINE_GENERIC | —/80/0/0/0 | — | E2_MEASURED |
| Liga | CALENDAR | 20/20/0/0/0 | 100 % | E2_MEASURED |

## Agrégation pondérée et comparaison E1B/E2

| Capacité | Ancres reçues/attendues | Nouvelles reçues/attendues | E2 reçu/attendu | U/I | Conclusion |
|---|---:|---:|---:|---:|---|
| TEAM | 20/20 | 180/180 | 200/200 | 0/0 | stable |
| PLAYER | 420/420 | 3 789/3 789 | 4 209/4 209 | 0/0 | stable, source lineup seulement |
| LINEUP | 20/20 | 180/180 | 200/200 | 0/0 | stable, reconstruction post-match |
| FORMATION | 20/20 | 180/180 | 200/200 | 0/0 | stable, reconstruction post-match |
| EVENTS | 179/— | 1 460/— | 1 639/— | 0/0 | volume descriptif |
| TEAM_STATISTICS | 20/20 | 180/180 | 200/200 | 0/0 | stable |
| PLAYER_STATISTICS | 420/420 | 3 788/3 789 | 4 208/4 209 | 1/1 | correctif ciblé |
| DISCIPLINE_GENERIC | 46/— | 357/— | 403/— | 0/0 | 3 fixtures vides valides |
| CALENDAR | 10/10 | 90/90 | 100/100 | 0/0 | couverture mesurée, temporalité à corriger |

Les agrégats utilisent les comptes `expected`; aucune moyenne simple des cinq
taux de ligue n'est utilisée. Les écarts entre ancres et nouvelles fixtures sont
descriptions, jamais interprétés comme relations causales.

Le seul écart de couverture se trouve sur une nouvelle fixture Liga de la strate
temporelle 6 : fixture `1208603`, objet signé
`2a106520004fcd3945b821db8130f2a671ad8ef7d17b83c8077fc495338c7135`.
Au grain joueur-fixture, 39 statistiques sur 40 attendues sont reliées aux joueurs
de lineup, avec une identité statistique hors grain et une valeur attendue
conservée en `UNKNOWN`. Aucune attribution n'est inventée.

## Concentration et limites

| Ligue | Équipes | Occurrences max | Part max des 40 places équipe-match |
|---|---:|---:|---:|
| Premier League | 20 | 4 | 10 % |
| Ligue 1 | 19 | 5 | 12,5 % |
| Bundesliga | 19 | 4 | 10 % |
| Serie A | 20 | 3 | 7,5 % |
| Liga | 20 | 5 | 12,5 % |

Cette diversité et la stratification temporelle décrivent l'échantillon ; elles
ne constituent pas une validation statistique de population. `EVENTS` et
`DISCIPLINE_GENERIC` n'ont pas de dénominateur d'occurrences inventé. `LINEUP` et
`FORMATION` restent des reconstructions post-match. `CALENDAR` est présent mais
la preuve ne démontre pas encore ce qui était connu avant le match.

## Progression locale

Candidates E3A :

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
DISCIPLINE_GENERIC
```

Correctifs ciblés avant E3A :

```text
PLAYER_STATISTICS = IDENTITY_OR_SCHEMA_INTEGRITY
CALENDAR = FINAL_STATE_NOT_KNOWN_AS_OF
```

Les capacités non évaluées par E2 conservent leur état antérieur. En particulier :

```text
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
3036 = 2681 + 206 + 149
```

Les 149 `ABSENCE_CAUSE_UNKNOWN` ne sont ni projetées par ligue, ni reclassées.

## Coûts, replay et sécurité

```text
GitHub Actions run = 31192408221
head = b04c35ed7d56a967fdaf479106a5fd014045d992
logical GET = 161
inventory GET = 1
receipt GET = 80
payload GET = 80
network bytes = 6434224
measurement duration = 107.347255 s
replay additional GET = 0
replay = BYTE_IDENTICAL
```

La réconciliation de synthèse post-run a été rejouée deux fois hors réseau et
est byte-identique. Elle ne change aucun compte source ; elle classe correctement
`PLAYER_STATISTICS` comme partielle et recalcule les hashes dérivés.

Toutes les actions interdites restent à zéro : API-Football, Odds, SQL distant,
R2 LIST/HEAD/write/delete, déploiement, publication, pari et promotion. Aucun
frontend n'a été modifié et aucun déploiement n'a été effectué.
