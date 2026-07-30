# Inventaire des fournisseurs — Historical Deep Data Harvest V1

État vérifié le 30 juillet 2026. Cet inventaire distingue les fournisseurs et
ne contient aucune valeur de secret.

## API-Football / API-Sports

- Rôle : fournisseur principal des rencontres et des données profondes.
- Authentification GitHub attendue : `API_FOOTBALL_KEY`.
- Présence du nom de secret : confirmée.
- Plan exigé par la campagne : `Mega`, actif.
- État du plan et quota : à prouver par `GET /status` dans le workflow 70.
- Écritures autorisées : uniquement dans le namespace R2 append-only
  `historical-deep-data/schema-v1/`.

## Football-Data.co.uk

- Rôle : corpus CSV historique de résultats, statistiques de match et cotes.
- Usage dans cette campagne : référence du marché historique et baseline
  cache-only ; aucun appel API payant.
- Authentification : non requise pour les CSV publics déjà intégrés.

## football-data.org

- Rôle : API distincte d’API-Football.
- Compte ou plan : non prouvé dans le dépôt.
- Présence d’un secret GitHub dédié : non observée.
- Usage dans cette campagne : aucun appel tant qu’un rôle et un accès distincts
  ne sont pas documentés.

## The Odds API

- Rôle : captures prospectives de prix.
- Authentification GitHub : le nom `ODDS_API_KEY` existe.
- Usage dans cette campagne : interdit. Aucun crédit historique ne doit être
  consommé par Historical Deep Data Harvest V1.

## Stockage et staging

- Les noms de secrets R2 attendus sont présents :
  `R2_ACCOUNT_ID`, `R2_BUCKET_NAME`, `R2_ACCESS_KEY_ID`,
  `R2_SECRET_ACCESS_KEY`.
- Le nom `DATABASE_URL` est présent, mais la campagne reste R2-first et ne doit
  écrire que dans un staging explicitement isolé. Aucune migration ni écriture
  destructive ne doit viser la base principale avant revue de la PR.

La présence d’un nom de secret ne prouve ni sa valeur, ni la disponibilité du
service, ni le niveau d’abonnement. Les workflows doivent échouer de manière
fermée lorsque cette preuve manque.
