# Modes de composition

## PRE_LINEUP

Le mode `PRE_LINEUP` contient uniquement ce qui est connaissable avant
l'annonce officielle :

- historique des titulaires ;
- absences prouvées avant cutoff ;
- forme et minutes antérieures ;
- scénario probabiliste uniquement s'il est explicitement modélisé ;
- aucun onze officiel futur.

Il ne peut pas utiliser la formation réelle du match cible ni présenter une
composition prédite comme une composition observée.

## POST_LINEUP

Le mode `POST_LINEUP` commence après la publication officielle et avant
kickoff. Il peut contenir :

- onze exact ;
- banc ;
- formation publiée ;
- changements par rapport à la baseline ;
- continuité et rôles présents.

Une observation doit porter un `observed_at` strictement antérieur au kickoff.
Un onze complet comporte exactement onze titulaires identifiés. Une réponse
partielle reste partielle.

## Séparation expérimentale

Les datasets, modèles et libellés publics sont séparés par mode. Un score
`POST_LINEUP` n'est jamais comparé comme s'il existait à T-24 h. Les métriques
ne sont comparées que sur un échantillon exactement apparié dans le même mode.

## État courant

Le cache contient 4 138 lignes équipes-lineups et 4 138 XI exacts, avec 4 127
formations/grilles complètes. Cette couverture de contenu concerne uniquement
la Ligue 1 et les observations sont `POST_MATCH_ONLY`.

`LINEUP_GATE=BLOCKED_BY_TEMPORALITY`. En conséquence :

- `PLAYER_PRELINEUP` n'est pas construit avec un onze futur ;
- `POST_LINEUP` n'est pas évalué ;
- les campagnes 11C, 11D et 11G restent bloquées ;
- 11E est terminée comme évaluation de gates : ses huit hypothèses restent
  bloquées individuellement ;
- 11F n'utilise que la baseline équipe dans un diagnostic descriptif
  rétrospectif non promouvable ;
- une lineup post-kickoff est rejetée par le garde temporel.
