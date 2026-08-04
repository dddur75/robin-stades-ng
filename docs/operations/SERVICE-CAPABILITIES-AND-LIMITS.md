# Capacités et limites des services

Le registre machine est `configs/platform/service-capabilities-v1.json`. Une
limite propre au compte reste `UNKNOWN` tant qu'elle n'est pas lue ou mesurée.

| Service | Capacité retenue | Limite/garde de mission | Source |
|---|---|---|---|
| GitHub Actions | orchestration | batches avant matrice; jobs nouveaux cible 15 min, max 20 | [limites officielles](https://docs.github.com/en/actions/reference/limits) |
| Cloudflare R2 | état durable append-only | prefixes/manifests; aucun scan global ou delete | [tarification officielle](https://developers.cloudflare.com/r2/pricing/) |
| Neon PostgreSQL | structuré, index, agrégats | pooler applicatif; direct seulement si requis; limites compte `UNKNOWN` | [pooling officiel](https://neon.com/docs/connect/connection-pooling) |
| ChatGPT Sites/Vinext | prototype privé léger | quota/entitlement `UNKNOWN`; aucune donnée live directe | [guide officiel](https://openai.com/academy/chatgpt-sites/) |
| API-Football | football profond | 0 appel par défaut; Mega publié 150k/jour | [plans officiels](https://www.api-football.com/pricing) |
| The Odds API | prix historiques | 0 crédit par défaut; prix absent → `NO_BET` | [API V4 officielle](https://the-odds-api.com/liveapi/guides/v4/) |
| Codex local | worktrees/tests | 40 h maximum, sans attente artificielle | observation locale |

## Règles d'exploitation

GitHub orchestre; R2 garde la preuve durable; PostgreSQL sert les données
structurées; Sites ne reçoit que des projections nettoyées. Les payloads
fournisseur bruts ne vont ni dans Git ni dans PostgreSQL.

Les connexions Neon groupées servent les applications et workers courts. Une
connexion directe est réservée aux migrations ou fonctions incompatibles avec
le pooler. Toute opération SQL importante définit `statement_timeout`,
`lock_timeout`, batches, plan d'exécution et staging.

Les coûts réels sont mesurés par opération. Une projection n'est jamais publiée
comme facture. L'audit du compte ou du plan n'autorise ni achat ni augmentation.
