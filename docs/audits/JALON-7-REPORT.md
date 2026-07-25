# Jalon 7 — rapport d’audit

## Preuve exécutée

État `historical-data@d25865e`, sans fournisseur : 8 familles, 4 691 prédictions,
612 fixtures OOS appariées pour les comparaisons principales, 68 groupes
saison-semaine et 5 000 réplications. Coût : 0 appel, 0 crédit.

| Comparaison | Δ Log Loss challenger-référence | CI 95 % | P(challenger meilleur) | Décision |
|---|---:|---:|---:|---|
| HGB vs multinomiale | +0,03455 | [0,01311 ; 0,05568] | 0,0004 | `INCONCLUSIVE` |
| sans forme récente vs multinomiale | -0,00370 | [-0,00709 ; -0,00033] | 0,9850 | résultat exposé, non promu |
| Poisson vs marché | +0,04963 | [0,02579 ; 0,07355] | 0,0000 | inférieur |
| Dixon–Coles vs Poisson | +0,00196 | [-0,00086 ; 0,00484] | 0,0930 | `INCONCLUSIVE` |
| joueurs pré-lineup vs équipe | +0,00056 | [-0,00267 ; 0,00372] | 0,3662 | `INCONCLUSIVE` |
| post-lineup vs pré-lineup | +0,03178 | [0,01557 ; 0,04784] | 0,0000 | inférieur |

Le filtre des prix non finis a été validé sur 408 paires Poisson/marché. Le
contrôle cible permutée donne Log Loss 1,12524 (`PASSED`). Baseline :
`JALON6_BASELINE_FROZEN`.
Production : `PRODUCTION_LOCKED`. Aucun candidat live.

## Limites

2024–2025 est désormais exposé. La validation externe multi-ligues est
préenregistrée mais non exécutée tant que les gates de couverture ne sont pas
atteints. Le backfill autonome continue indépendamment.
