# Gates de promotion

Un pattern devient `LIVE_SHADOW_CANDIDATE` uniquement si les 17 critères
ci-dessous sont simultanément vrais.

| # | Critère | 11A |
|---:|---|---|
| 1 | data gate `READY` | non, `TEAM_GATE=PARTIAL` |
| 2 | aucune fuite | non prouvée au niveau `observed_at` source |
| 3 | support préenregistré | oui |
| 4 | au moins trois périodes éligibles | oui |
| 5 | direction stable | non |
| 6 | dernier fold positif | non |
| 7 | BH famille sous seuil | non, q = 0,9638269 |
| 8 | contrôle global acceptable | non, q = 1 |
| 9 | permutation acceptable | non, p = 0,961 |
| 10 | borne bootstrap cohérente | non |
| 11 | concentration acceptable | non démontrée |
| 12 | score incrémental positif vs marché | non |
| 13 | ROI historique observé non artificiel | non calculé |
| 14 | règle compréhensible | oui |
| 15 | information disponible en live | non prouvée |
| 16 | marché live avec `observed_at` exact | non |
| 17 | décision reproductible avant kickoff | non |

## Politique fail-closed

- `all(criteria)` est la seule condition de promotion ;
- une clé absente vaut échec, jamais succès ;
- un dataset bloqué ne peut pas contourner son gate ;
- une cote simulée ne ferme pas le gate marché ;
- un statut de watchlist n'autorise ni décision ni mise ;
- aucune promotion historique ne reçoit le statut `VALIDATED`.

## État courant

14 critères échouent. Le test principal ne démontre aucun gain contre le marché
recalibré ; `TEAM_GATE` est partiel et le prix historique est
`SOURCE_PRICE_CLASS_ONLY` sans `observed_at` exact pour une décision live.

```text
LIVE_SHADOW_CANDIDATE=0
PROSPECTIVE_WATCHLIST=0
SHADOW_DECISIONS=0
STAKE_UNITS=0
```

La valeur interne d'un objet d'évaluation ne crée pas à elle seule une entrée
de watchlist : seule la sortie matérialisée et enregistrée compte. Cette sortie
est vide.
