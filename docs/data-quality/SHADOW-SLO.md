# SLO shadow

| Indicateur | Cible | Mesure initiale |
|---|---:|---:|
| succès workflows | ≥ 95 % | observation insuffisante |
| couverture fenêtres éligibles | ≥ 90 % | observation insuffisante |
| provenance complète | 100 % | 100 % |
| réserve quota | ≥ 20 % | 99,96 % |
| pertes silencieuses | 0 | 0 |
| doublons non résolus | 0 | 0 |
| fuites temporelles | 0 | 0 |
| secrets exposés | 0 | 0 |
| démo présentée comme live | 0 | 0 |
| décisions avec motif | 100 % | 100 % |
| rejets avec code | 100 % | 100 % |

Une cible sans dénominateur suffisant reste `INSUFFICIENT_OBSERVATION`. Les
contrôles sont calculés depuis le registre durable et exposés dans Cockpit Live
V2. Une dégradation bloque les décisions dépendantes ; elle ne peut jamais
dégrader silencieusement la provenance ni déverrouiller la production.
