# Politique de titulaire habituel

## Principe

Un titulaire habituel est défini uniquement avec les rencontres antérieures au
fixture cible. Le statut du match cible ne peut ni créer ni confirmer la
baseline.

## Baseline générale

Pour chaque fold :

1. ordonner les apparitions par kickoff ;
2. ne conserver que les observations antérieures au cutoff ;
3. compter titularisations, minutes et récence dans la fenêtre gelée ;
4. exposer le support et l'incertitude ;
5. marquer `INSUFFICIENT_HISTORY` si le support minimal n'est pas atteint.

Le rôle et le poste viennent d'une source observée. Ils ne sont jamais déduits
du nom du joueur.

## Défenseurs centraux

La baseline d'un défenseur central utilise les huit rencontres précédentes :

- poste central observé ;
- au moins quatre titularisations, ou seuil de minutes préenregistré ;
- aucune information du match cible ;
- expiration du roster et changements de club pris en compte ;
- support conservé avec le résultat.

Cette baseline permettrait de calculer le nombre de centraux habituels absents,
la continuité du duo et un duo nouveau. Une paire annoncée au match cible ne
doit pas réécrire l'historique.

## Gardien

Le gardien habituel suit la même politique : historique antérieur, identité
sourcée, club valide et aucune déduction depuis le onze cible.

## État courant

`STARTER_BASELINE_GATE=BLOCKED_BY_TEMPORALITY`.

La version historique V1 utilise une récence du dernier enregistrement plutôt
que du dernier départ et ne prouve pas complètement l'expiration des rosters
ni la lignée source-time. H11-001, H11-004 et H11-005 restent donc bloquées.

Le run autoritatif `30282406035` confirme le blocage temporel sans reconstruire
de titulaire. La source auditée est
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`.
