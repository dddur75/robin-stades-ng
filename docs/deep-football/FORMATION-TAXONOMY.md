# Taxonomie des formations

## Valeurs normalisables

La taxonomie conserve la valeur brute, la valeur normalisée, la confiance et
l'éventuelle ambiguïté. Les libellés explicitement supportés sont :

```text
4-3-3
4-2-3-1
4-4-2
4-1-4-1
3-4-3
3-5-2
5-3-2
5-4-1
```

Une notation ambiguë n'est jamais forcée vers une classe.

## Familles tactiques

```text
BACK_FOUR
BACK_THREE
BACK_FIVE
MIDFIELD_THREE
MIDFIELD_FOUR
FRONT_THREE
FRONT_TWO
SINGLE_STRIKER
```

Une formation peut appartenir à plusieurs familles structurelles. Les règles
de correspondance sont versionnées et ne changent pas après lecture du
résultat.

## Continuité tactique

La formation habituelle utilise les cinq matchs antérieurs. Les sorties
possibles sont continuité, changement, nouveauté ou insuffisance de support.
Le match cible n'entre pas dans sa propre baseline.

## Matchups

Une interaction telle que 4-3-3 contre 4-4-2 est une
`ADJUSTED_ASSOCIATION`. Elle doit être ajustée au minimum pour le marché, le
domicile, la ligue, la saison, la force, le repos et la continuité. Un simple
compte de victoires est interdit.

## État courant

4 127 formations d'équipe sont présentes en Ligue 1, mais leur instant
pré-kickoff n'est pas prouvé. `FORMATION_GATE=BLOCKED_BY_TEMPORALITY`.
H11-002, H11-007 et H11-008 ne sont donc pas exécutées. Le contrôle de
formation décalée reste lui aussi `DATA_GATE_BLOCKED`.

Le run autoritatif `30282406035` confirme ce gate sans requalifier le contenu
post-match. La source auditée est
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`.
