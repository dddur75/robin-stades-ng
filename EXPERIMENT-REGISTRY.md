# Registre des expériences

## Jalon 5

| Expérience | Question | État |
|---|---|---|
| J5 Dataset Factory V1 | Les features d’équipe sont-elles reproductibles sans fuite ? | `VERIFIED_LEGACY` |
| J5 Elo OOS | La baseline reste-t-elle calibrée sur 2024–2025 ? | `OOS_BACKTEST_V1_READY` |
| J5 API-Football pilote | La Ligue 1 2025 est-elle profondément couverte ? | `HISTORICAL_PILOT_ACTIVE` |
| J5 Player lift | Les variables joueurs améliorent-elles l’OOS ? | `BLOCKED_BY_COVERAGE` |

## Expériences antérieures

| Expérience | Question | État |
|---|---|---|
| Vague 1 | Les hypothèses pré-enregistrées battent-elles le prix ? | `PARTIAL` |
| Vague 1B | Les hypothèses complémentaires résistent-elles séparément ? | `PARTIAL` |
| Vague 2 | Des combinaisons d'atomes produisent-elles un lift ? | `UNVERIFIED` |
| Vague 2B | Le lift survit-il à une référence ajustée au marché ? | `PARTIAL` |
| Confrontation | Les candidats conservent-ils un edge prospectif ? | `IN_PROGRESS` |
| J2 OOS 2025–2026 | Les stratégies simples résistent-elles en walk-forward ? | `VERIFIED_NO_PROMOTION` |
| Shadow V1 Ligue 1 | Les décisions restent-elles reproductibles prospectivement ? | `INFRASTRUCTURE_READY` |
| Burn-in Jalon 4 | La chaîne reste-t-elle durable, complète et récupérable ? | `ACTIVE_DESCRIPTIVE_ONLY` |

La distinction obligatoire est :

`BACKTEST EXPLORATOIRE` → `HORS ÉCHANTILLON` → `SHADOW TEST` → `PRODUCTION`.

Le dépôt ne fournit encore aucun résultat au stade `PRODUCTION`. Le résultat
Over 2,5 observé en OOS reste inconclusif et n'est pas mélangé aux futures
performances shadow.
