# Gate de pied fort

## Conditions gelées

`FOOTEDNESS_GATE` ne peut être `READY` que si :

- le pied est observé et sourcé ;
- la couverture des joueurs pertinents atteint 90 % ;
- l'identité est résolue ;
- la temporalité et la provenance sont conservées ;
- aucune valeur n'est remplie par heuristique ou déduite du poste.

## Usages autorisés lorsque le gate est prêt

- proportions droite/gauche par unité ;
- ailier inversé ;
- latéral sur pied naturel ou opposé ;
- composition du duo central ;
- asymétrie attaque/défense ;
- interaction côté fort/côté faible.

Ces features restent soumises au gate lineup et au cutoff.

## État courant

```text
FOOTEDNESS_DATA_GATE=BLOCKED
FOOTEDNESS_GATE=BLOCKED_BY_COVERAGE
```

Le cache des joueurs et effectifs ne contient aucun champ de pied préféré
observé : couverture 0 %. Aucun scraping, enrichissement heuristique ou
inférence n'a été effectué.

H11-003 et la campagne de matchup de latéralité sont bloquées. Le contrôle
`false_footedness` est enregistré mais ne produit aucun faux edge. Le coût
fournisseur potentiel reste non estimé tant qu'une source licite et
point-in-time n'est pas identifiée ; aucun appel n'est autorisé dans ce jalon.

Le run cache-only autoritatif `30282406035` confirme une couverture sourcée
nulle, le gate fermé et 0 appel fournisseur. La source auditée est
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`.
