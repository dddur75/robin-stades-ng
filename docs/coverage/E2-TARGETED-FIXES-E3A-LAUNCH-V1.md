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
classification additive.

Le contrat Calendar est mécaniquement testé sur un Golden Pack synthétique. Il
distingue strictement charge planifiée et charge jouée, applique
`known_at < cutoff` et échoue vers `UNKNOWN` quand la complétude à la date n'est
pas prouvée. Il ne déclare pas `CALENDAR_READY_STRICT` et impose une future
vérification E3A réelle avant toute promotion.

Ce lot n'exécute ni E3A, ni E3B, ni masque, propriété, paire, triple ou backtest.
Son verdict scientifique demeure `PASS_AND_HOLD`.
