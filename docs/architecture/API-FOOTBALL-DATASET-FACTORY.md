# API-Football Dataset Factory

La factory lit exclusivement les Parquet et observations restaurés. Elle
rejoint les payloads sans `fixture_id` embarqué grâce au hash du payload et aux
paramètres de l'observation brute.

## Datasets

- `api_team_pre_match_v1` : features équipes calculées avant mise à jour par la
  fixture cible.
- `api_player_match_facts_v1` : faits joueur-match `POST_MATCH_ONLY`.
- `player_feature_store_v1` : valeurs longues par joueur, fixture et
  `as_of_time`.
- `api_player_pre_lineup_v1` : onze attendu depuis l'historique antérieur.
- `api_post_lineup_simulated_v1` : composition cible explicitement
  `HISTORICAL SIMULATED`.
- `api_market_baseline_v1` : marché legacy rapproché, dévigué et marqué
  `HISTORICAL_CLOSING_MARKET`.

Chaque manifest contient version, saisons, lignes, fixtures, features, cibles,
couverture, politique temporelle, révision et SHA-256. Les faits volumineux
restent en Parquet ; les manifests et synthèses vont dans PostgreSQL.

## Reproductibilité

Le calcul est déterministe. Le temps logique d'une feature est son cutoff
`as_of_time`; l'heure murale du run reste dans le manifest. Un replay ne
rappelle aucun fournisseur et déduplique sur le hash canonique.

