# Migration legacy vers UUID internes

Date : 2026-07-24  
Dataset source : `data/matches.parquet`  
Principe : migration non destructive, déterministe, rejouable.

## Résultat mesuré

| Mesure | Valeur |
|---|---:|
| Lignes examinées | 36 423 |
| Correspondances produites | 37 024 |
| `EXACT` | 9 |
| `PROVIDER_CONFIRMED` | 0 |
| `RULE_MATCHED` | 36 522 |
| `PROBABLE` | 493 |
| `AMBIGUOUS` | 0 |
| `UNRESOLVED` | 0 |
| `REJECTED` | 0 |
| Collisions | 0 |
| Couverture certaine | 98,67 % |

## Interprétation

Les neuf compétitions sont exactes par code source. Les saisons et fixtures sont
reliées par des clés métier contrôlées : compétition, saison, date, domicile et
extérieur. Les 493 équipes/arbitres ne disposent que d'un nom legacy contextualisé
par compétition ; elles restent donc `PROBABLE`, avec confiance 0,65, et sont
exclues des modèles exigeant une identité certaine.

`PROBABLE` n'est jamais promu implicitement. Une future source portant des
identifiants stables pourra confirmer ou rejeter ces liens.

## Reprise et traçabilité

- les UUID sont déterministes à partir d'une clé canonique versionnée ;
- deux exécutions produisent le même registre ;
- le fichier legacy n'est jamais modifié ;
- les ambiguïtés sont exportées séparément ;
- le journal JSON contient les compteurs et la couverture ;
- les collisions provoquent un contrôle bloquant.

Artefacts :

- `data/migrations/jalon2/legacy-uuid-mappings.parquet` ;
- `data/migrations/jalon2/legacy-uuid-ambiguities.csv` ;
- `data/migrations/jalon2/legacy-uuid-summary.json`.
