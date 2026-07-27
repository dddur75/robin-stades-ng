# Politique des absences

## Définition recevable

Une absence est recevable uniquement si son indisponibilité est observée et
datée avant le cutoff du fixture, avec :

- joueur identifié sans ambiguïté ;
- source et instant d'observation ;
- type et statut conservés tels qu'observés ;
- rôle résolu depuis une donnée source ;
- lignée jusqu'au fixture cible.

Une non-titularisation, une absence de la feuille de match ou le résultat final
ne constituent jamais une preuve d'absence.

## Gate

`ABSENCE_GATE` exige :

- preuve pré-match ;
- identité joueur ≥ 99 % ;
- rôle résolvable ;
- couverture par saison suffisante ;
- aucune reconstruction depuis le onze final.

Les statuts autorisés sont `READY`, `PARTIAL`, `BLOCKED_BY_COVERAGE`,
`BLOCKED_BY_TEMPORALITY`, `BLOCKED_BY_IDENTITY` et `MARKET_UNAVAILABLE`.

## Features conditionnelles

Quand le gate est prêt, les features peuvent mesurer :

- contribution antérieure indisponible ;
- gardien habituel absent ;
- nombre de centraux habituels indisponibles ;
- minutes défensives indisponibles ;
- rupture de la colonne vertébrale ;
- disponibilité d'un remplacement.

Chaque feature conserve `null` lorsqu'un composant manque.

## État courant

Les 12 801 lignes historiques de blessures sont
`HISTORICAL_NON_POINT_IN_TIME`. Elles ne prouvent pas ce qui était connu avant
kickoff. Le gate est donc `BLOCKED_BY_TEMPORALITY`.

Conséquences :

- H11-001, H11-004 et H11-006 sont bloquées ;
- aucun contrôle « absence décalée » n'est utilisé pour promouvoir un signal ;
- aucun appel fournisseur n'est autorisé pour combler ce gate ;
- aucune collecte P3/P4 n'est relancée.

Le run cache-only autoritatif `30282406035`, source
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`, confirme ce
blocage avec 0 appel fournisseur et sans construire d'absence artificielle.
