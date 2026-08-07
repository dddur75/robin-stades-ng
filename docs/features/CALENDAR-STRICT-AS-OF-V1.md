# Calendar Strict As-Of V1

Ce contrat construit les variables calendrier avec les seules révisions dont
`known_at < cutoff`. Il ne lit aucune donnée réelle, ne promeut pas `CALENDAR`
et n'autorise pas E3A. Le statut maximal de ce lot est
`CALENDAR_STRICT_ASOF_MECHANICALLY_VALIDATED` ; `CALENDAR_READY_STRICT` reste
interdit avant une exécution E3A réelle.

## Deux charges distinctes

- `SCHEDULED_LOAD` compte les fixtures connues comme planifiées, en cours,
  terminées ou abandonnées. Elle sert aux indicateurs de congestion.
- `PLAYED_LOAD` compte seulement les fixtures dont le statut `FINISHED` était
  connu avant le cutoff. Elle sert aux comptes de matchs passés et au repos.

Les fixtures annulées ou reportées avant le cutoff sont exclues. Un report connu
après le cutoff ne peut pas modifier la vue antérieure : la dernière révision
déjà connue reste la seule admissible. Une reprogrammation utilise de la même
façon le dernier kickoff connu. Une fixture commencée mais non terminée compte
dans `SCHEDULED_LOAD`, jamais dans `PLAYED_LOAD`.

## Politique UNKNOWN

Si la fixture cible n'était pas connue au cutoff, ou si la complétude du
catalogue à cette date n'est pas prouvée, toutes les variables sont `UNKNOWN`.
L'implémentation ne convertit jamais `UNKNOWN` en `0` ou `FALSE`.
Un cutoff postérieur au kickoff cible est également rejeté avec
`CUTOFF_NOT_PREMATCH` et toutes les variables à `UNKNOWN`.

## Variables

Le contrat versionné couvre les jours de repos domicile/extérieur, les matchs
sur 7/14/28 jours, les séries de déplacements, le troisième déplacement
consécutif, les jours depuis le dernier match au lieu correspondant et les trois
fenêtres de congestion. Les seuils de congestion sont gelés dans
`configs/features/calendar-strict-asof-v1.json`.

## Golden Pack synthétique

Le pack contient quatorze fixtures, deux équipes et plusieurs cutoffs. Il couvre
un match terminé, un match en cours, un report connu avant et après cutoff, une
annulation, un abandon, une reprogrammation, deux fixtures le même jour, une
arrivée tardive, ainsi qu'une fixture future connue et une future inconnue. Les
tests calculent deux fois chaque vue et exigent des octets identiques, avec des
résultats `TRUE`, `FALSE` et `UNKNOWN`.
