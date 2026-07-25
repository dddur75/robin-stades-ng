# Player Feature Store V1

Le store est long et versionné. Sa clé logique associe `feature_name`,
`feature_version`, `player_id`, `team_id`, `fixture_id` et `as_of_time`.

Familles livrées : minutes sur 5/10 matchs et 7/14/30 jours, titularisations,
entrées, buts, passes, tirs, tirs cadrés, forme, volatilité, contributions
offensive/défensive, importance de rôle, support en minutes, force régularisée,
incertitude et fatigue estimée.

La force applique une régularisation `minutes / (minutes + 900)`. Elle expose
ses composantes et son support ; elle n'invente ni valeur marchande ni zéro.
Après transfert, le `player_id` fournisseur reste identique et l'ancienne
appartenance quitte l'effectif actif.

