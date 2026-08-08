# P0 E3A Capability Scale V1

E3A est gelé sur la Ligue 1 API-Football 2024 : 308 fixtures terminales, 19 objets
de source et 12 702 015 octets logiques. Ce choix découle de la politique ordonnée
committée : Ligue 1 et Bundesliga ont le plus petit nombre d'objets, puis Ligue 1 a
le plus petit volume logique. La liste des fixtures et l'allow-list exacte ne sont
publiées que dans `e3a-selection-manifest-v1.json`.

La lecture scientifique déduplique par clé métier et contenu. Les champs de
provenance et d'ingestion ne déterminent jamais l'identité d'un fait. `UNKNOWN`
n'est jamais converti en zéro ou en faux.

TEAM et PLAYER restent des identités. LINEUP et FORMATION sont descriptifs
reconstruits. EVENTS, TEAM_STATISTICS et DISCIPLINE_GENERIC ne sont utilisables
que comme cibles du match ou comme sources laggées issues de matchs strictement
antérieurs. Aucune de ces capacités n'est un prédicteur direct du match cible.

Calendar conserve le Golden Pack synthétique, mais les objets réels n'exposent ni
catalogue de révision ni `known_at`. Les 17 variables réelles restent donc
`UNKNOWN` et Calendar est `BLOCKED_BY_SOURCE`, jamais `READY_STRICT`.

Le transport d'exécution est exclusivement GitHub Artifact par identifiants et
digests immuables. L'exécution ne monte aucun secret R2, fournisseur, SQL ou Odds.

