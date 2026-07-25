# Phases canoniques UCL

Phases autorisées : `QUALIFYING`, `PLAYOFF`, `GROUP_STAGE`, `LEAGUE_PHASE`,
`KNOCKOUT`, `FINAL`, `CANCELLED`, `DUPLICATE`, `UNKNOWN`.

`ucl_main_competition_v1` contient phase de groupes/de ligue et élimination
directe. `ucl_qualifying_v1` contient qualifications et play-offs. Le TEAM_GATE
analytique porte uniquement sur le dataset principal. Les phases inconnues ne
sont jamais absorbées silencieusement.

Preuve initiale : 981 fixtures dans le périmètre principal après reconnaissance
de `League Stage`, 613 en qualifications/play-offs. L’identité du périmètre
principal est résolue par identifiant fournisseur.
