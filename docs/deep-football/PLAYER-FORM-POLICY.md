# Politique de forme joueur

## Grain et cutoff

La forme est calculée pour un joueur et un fixture cible à partir de ses
apparitions strictement antérieures. L'unité de fenêtre est l'apparition, pas le
match calendaire de l'équipe. Un joueur qui n'a pas joué ne crée pas une
apparition artificielle.

## Définitions gelées

```text
GOALS_LAST_3_APPEARANCES >= 2
GOALS_LAST_5_APPEARANCES >= 3
GOAL_INVOLVEMENTS_LAST_5 >= 4
MINUTES_LAST_3 >= 180
```

Les fenêtres et seuils sont des hypothèses de domaine préenregistrées. Ils ne
sont pas retunés selon le ROI.

Les agrégats autorisés incluent :

- minutes et titularisations antérieures ;
- buts, passes décisives, tirs et implications antérieurs ;
- part des minutes et des buts de l'équipe ;
- support en apparitions ;
- statut explicite d'insuffisance.

## Valeurs manquantes

- aucune apparition antérieure : `INSUFFICIENT_PRIOR_APPEARANCES` ;
- moins de trois apparitions : valeur possible avec support, gate non fermé ;
- donnée buts absente : `null`, pas zéro ;
- remplaçant non utilisé : exclu d'une fenêtre d'apparitions ;
- identité ambiguë : observation rejetée.

## Anti-fuite

Le match cible, les événements du match cible et toute donnée ingérée après le
cutoff sont interdits. Les agrégats sont reconstruits fold par fold. Le
classement « joueur en forme » ne peut pas être déduit du résultat futur.

## État courant

`PLAYER_FORM_GATE=BLOCKED_BY_TEMPORALITY`.

Les données profondes sont limitées à la Ligue 1 et marquées
`POST_MATCH_ONLY`. Les fenêtres V1 incluent des remplaçants non utilisés et le
champ de buts présente une ambiguïté null/zéro. Aucune hypothèse de forme joueur
n'est donc exécutée ni promue dans le Jalon 11.

Le run autoritatif `30282406035` confirme ce statut depuis
`historical-data@033a98b11b80c059f8986c33c69f1401ce8cf05c`, sans imputation
artificielle, appel fournisseur ni ouverture du gate.
