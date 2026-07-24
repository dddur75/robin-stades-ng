# Registre des stratégies

## Strategy Factory Jalon 5

| Stratégie | Modèle | Période | N | ROI | Statut |
|---|---|---|---:|---:|---|
| Edge 5 %, mise fixe | Elo V1 | OOS 2024–2025 | 4 139 | -8,55 % | `REJECTED` |

Le résultat est négatif et ne déclenche aucune promotion. La stratégie reste
historique et simulée ; `PRODUCTION_LOCKED` est obligatoire.

| Famille | Version | Usage | Statut |
|---|---:|---|---|
| Vague 1 | 1.0 | 66 hypothèses pré-enregistrées | `PARTIAL` |
| Vague 1B | 1.0 | famille annexe séparée | `PARTIAL` |
| Vague 2 | 1.0 | exploration combinatoire brute | `UNVERIFIED` |
| Vague 2B | 1.0 | référence ajustée par cellules de marché | `PARTIAL` |
| Confrontation CP-01 à CP-10 | 1.0 | suivi prospectif | `IN_PROGRESS` |
| Favori marché | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Favori domicile | J2-OOS | baseline walk-forward | `REJECTED_OOS` |
| Seuil probabilité 55 % | J2-OOS | consensus Elo–Poisson | `REJECTED_OOS` |
| Value simple edge 4 % | J2-OOS | prix dé-viggé | `REJECTED_OOS` |
| Over 2,5 value | J2-OOS | Poisson vs marché | `INCONCLUSIVE_OOS` |
| BTTS | J2-OOS | odds legacy absentes | `INSUFFICIENT_SAMPLE` |

Règles globales :

- mise réelle interdite ;
- holdout 2025-26 scellé tant qu'une décision formelle ne l'ouvre pas ;
- une stratégie rentable en exploration reste `UNVERIFIED` ;
- le passage à `PRODUCTION_READY` exige hors échantillon, robustesse, coûts,
  concentration des gains, drawdown et shadow test.

## Burn-in Jalon 4

Zéro stratégie est promue. Une décision live a été rejetée et aucun pari shadow
n’est accepté ou réglé. Le legacy, l’OOS historique et le prospectif live restent
trois populations séparées.
