# Feature Contract V2

## Objet

Chaque feature profonde est une observation versionnée, traçable et
reproductible. Le contrat est figé avant lecture des performances.

## Champs obligatoires

| Champ | Règle |
|---|---|
| `feature_name` | nom stable et explicite |
| `feature_version` | version sémantique |
| `entity` | grain, par exemple `TEAM_FIXTURE` ou `PLAYER_FIXTURE` |
| `source` | source(s) observée(s), jamais implicite |
| `available_at` | `PRE_MATCH`, `PRE_LINEUP` ou `POST_LINEUP` |
| `cutoff_policy` | règle stricte d'antériorité |
| `lookback` | type, longueur et unité gelés |
| `missing_policy` | `MISSING_NOT_ZERO` par défaut |
| `unit` | points, buts, minutes, jours, proportion, etc. |
| `allowed_markets` | marchés pour lesquels l'usage est recevable |
| `allowed_research_modes` | modes temporels autorisés |
| `quality_gate` | gate qui doit être `READY` |
| `leakage_tests` | tests adversariaux exigés |
| `provenance` | dataset, fournisseur et lignée |
| `dataset_version` | version du dataset de sortie |
| `contract_hash` | SHA-256 du contrat canonique |

Une feature dont une entrée est absente reste `null`. Un indicateur de
missingness peut être construit ; la valeur source ne devient jamais zéro.

## Dataset construit

`TEAM_PREMATCH`, version `deep-football-team-prematch-v2` :

- 10 732 lignes ;
- cinq ligues et saisons 2020–2025 ;
- cutoff `TARGET_KICKOFF_EXCLUSIVE_STATE_BEFORE_UPDATE` ;
- mode `PRE_LINEUP` ;
- hash logique
  `2c73aa3bab4683fd9ec6fead1d7700e3681f85625182b885c00b7095a5a873d6` ;
- SHA-256 Parquet
  `d871477dc8d830726869c173b742e5fb57bf95ff06094613a5ff1ce7baa11673` ;
- 2 000 155 octets, stockés hors Git.

Le target n'entre pas dans sa propre rolling window : la ligne est émise avant
la mise à jour par le résultat cible. En revanche, les 10 732 frontières sont
égales au kickoff et la preuve `source_observed_at` n'existe pas ligne par
ligne. Le contrat est donc `TEAM_GATE=PARTIAL`, utilisable seulement en
diagnostic descriptif.

Features produites :

```text
elo_difference
home_form_5
away_form_5
home_form_10
away_form_10
home_goals_for_5
away_goals_for_5
home_goals_against_5
away_goals_against_5
home_rest_days
away_rest_days
```

Les fenêtres 3/5/10 sont définies dans le code, mais seules les features
explicitement listées par le manifeste entrent dans cette version du dataset.

## Missingness observée

| Famille | Domicile | Extérieur |
|---|---:|---:|
| forme 5/10 | 0,158 % | 0,214 % |
| buts pour/contre 5 | 0,158 % | 0,214 % |
| repos | 0,158 % | 0,214 % |
| différence Elo | 0 % | 0 % |

Les imputations de modèles sont ajustées uniquement sur le train du fold et
accompagnées d'indicateurs de valeur manquante.

## Datasets bloqués

| Dataset | Statut |
|---|---|
| `PLAYER_PRELINEUP` | `PLAYER_FORM_AND_STARTER_BASELINE_GATES_BLOCKED` |
| `POST_LINEUP` | `LINEUP_TEMPORAL_GATE_BLOCKED` |
| `FORMATION_MATCHUP` | `FORMATION_TEMPORAL_GATE_BLOCKED` |
| `FOOTEDNESS_MATCHUP` | `FOOTEDNESS_COVERAGE_GATE_BLOCKED` |

Un dataset bloqué n'est ni construit artificiellement ni substitué par une
simulation présentée comme observation.
