# Résultats de validation externe V1

État : `WAITING_FOR_EXTERNAL_GATES`.

Le protocole a été gelé avant mesure sous le hash
`53932dff3a30038668230b493746d3d7e7f45cbd4c9f967191e934da853645d2`.
Trois ligues franchissent TEAM_GATE : Premier League, La Liga et Bundesliga.
Les évaluations portent sur 2 136 fixtures 2024–2025 exactement appariées.
Le résultat durable provient du run GitHub `30167355305`, exécuté avec
`provider_calls = 0` et `quota_consumed = 0`.

| Famille | Log Loss | Brier | ECE | Accuracy |
|---|---:|---:|---:|---:|
| Transfert Ligue 1 gelé | 0,9945 | 0,1976 | 0,0195 | 51,36 % |
| League-specific | 0,9983 | 0,1980 | 0,0262 | 51,73 % |
| Pooled | 0,9958 | 0,1980 | 0,0261 | 51,12 % |
| Poisson | 1,0317 | 0,2063 | 0,0147 | 48,17 % |
| Dixon–Coles | 1,0312 | 0,2063 | 0,0157 | 48,41 % |

Comparaisons :

- league-specific vs transfert : Δ Log Loss +0,00376,
  CI 95 % [-0,00288 ; +0,01078], inconclusif ;
- league-specific vs pooled : +0,00246,
  CI 95 % [-0,00251 ; +0,00753], inconclusif ;
- Dixon–Coles vs Poisson : -0,00051,
  CI 95 % [-0,00229 ; +0,00132], inconclusif ;
- Poisson vs league-specific : +0,03338,
  CI 95 % [+0,01936 ; +0,04685], échec externe du challenger score.

Les comparaisons au marché sont `UNAVAILABLE` : aucun prix historique externe
fiable n’est présent. Aucun résultat ne peut donc devenir stratégie ou candidat
shadow. Statut scientifique : `NO_EXTERNAL_VALIDATED_EDGE`.
