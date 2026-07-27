# Gates des données prospectives

Les gates sont évalués par fixture, puis agrégés sans masquer les échecs.

## PROSPECTIVE_PLAYER_GATE

- au moins trois captures antérieures ou une politique explicite ;
- identités joueur/équipe cohérentes ;
- fenêtres admissibles ;
- aucune information du match cible après cutoff.

## PROSPECTIVE_INJURY_GATE

- statut réellement observé ;
- joueur identifié ;
- source et reçu enregistrés ;
- `response_received_at < cutoff_at`.

Une blessure historique post-match ne ferme pas ce gate.

## PROSPECTIVE_LINEUP_GATE

- exactement onze titulaires distincts ;
- payload complet ;
- identités cohérentes ;
- réception avant kickoff et avant le cutoff déclaré.

## PROSPECTIVE_FORMATION_GATE

- lineup gate vert ;
- formation présente et normalisable ;
- aucune ambiguïté critique ;
- même preuve temporelle que la lineup utilisée.

## PROSPECTIVE_MARKET_GATE

- fixture appariée sans ambiguïté ;
- bookmaker et marché explicites ;
- sélection, cote et marge présentes ;
- `observed_at` exact ;
- payload et reçu vérifiables.

## Statuts et agrégation

Un gate expose `status`, `passed`, `total`, raisons, fenêtres et hashes de
preuve. Une couverture agrégée ne ferme pas un gate individuel. Le statut
global le plus favorable autorisé est borné par les fixtures en échec.

`CAPTURED_EMPTY`, `MISSED_WINDOW`, `TEMPORALITY_FAILED` et `IDENTITY_FAILED`
restent visibles dans le dénominateur.

## Features conditionnelles

Les features joueur en forme, minutes 3/5, titulaire habituel, gardien et
centraux habituels nécessitent le player gate. Absences, deux centraux absents
et retour de blessure nécessitent l’injury gate. Continuité, nouveau duo et
changements d’onze nécessitent le lineup gate. Formation et changement de
formation nécessitent le formation gate. Les prix à chaque fenêtre nécessitent
le market gate.

Repos et congestion n’utilisent que des fixtures antérieures vérifiées. Le
match cible est exclu.

## H11

H11-001 à H11-008 restent gelées avec leur minimum d’origine. L’observatoire
calcule données requises, fenêtres nécessaires, observations, couverture,
première date possible et statut. Aucun test statistique n’est lancé avant le
minimum préenregistré.
