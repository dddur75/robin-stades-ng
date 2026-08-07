# E2 Targeted Fixes and E3A Launch V1

Ce lot est additif. Il ne modifie ni E1A, ni E1B, ni les rapports E2 historiques.
La PR #34 a été fusionnée au head `841ae4d850ceba4f6a7dc230ad3c4ce40de80364`
par le merge commit `ba928d096e12dbffaea96bbd67770a313257433a`, puis
la CI de `main` a terminé verte.

L'audit explique les 33 467 lignes ajoutées : 23 853 lignes sont les 855 strates
temporelles granulaires et 2 319 lignes la sélection autoritative des 100
fixtures. Aucune seconde liste détaillée des fixtures, aucun payload brut et
aucun fichier temporaire ne sont suivis. Verdict : `NO_COMPACTION_REQUIRED`.

La cause exacte de l'écart `PLAYER_STATISTICS` n'est pas contenue dans Git. Le
diagnostic autorisé est limité au reçu et au payload exacts de la fixture
`1208603`, deux GET et cinq mégaoctets maximum. Les rapports historiques restent
`40 expected / 39 received / 1 UNKNOWN / 1 invalid` quelle que soit la nouvelle
classification additive. La lecture exacte a confirmé 40 identités lineup
uniques et 40 identités statistiques uniques, mais seulement 39 dans leur
intersection : l'identité `405681` est absente des statistiques et l'identité
`496425` est présente hors du grain lineup. Aucun doublon, identifiant nul ou
rattachement d'équipe contradictoire n'est observé. La cause est classée
`PROVIDER_INCONSISTENCY`, sans correctif de code ; `missing_player_stat_row`
reste explicitement `UNKNOWN`.

Le contrat Calendar est mécaniquement testé sur un Golden Pack synthétique. Il
distingue strictement charge planifiée et charge jouée, applique
`known_at < cutoff` et échoue vers `UNKNOWN` quand la complétude à la date n'est
pas prouvée. Il ne déclare pas `CALENDAR_READY_STRICT` et impose une future
vérification E3A réelle avant toute promotion.

Le nouveau set de lancement conserve les sept candidates E2 et ajoute seulement
`CALENDAR` comme candidate à une vérification E3A réelle. `PLAYER_STATISTICS`
reste bloquée jusqu'à l'acceptation scientifique de la politique `UNKNOWN` sur
un périmètre E3A gelé.

Ce lot n'exécute ni E3A, ni E3B, ni masque, propriété, paire, triple ou backtest.
Son verdict scientifique demeure `PASS_AND_HOLD`.
