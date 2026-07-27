# Politique des fenêtres de capture

Version : `prospective-capture-window-v1`.

Source machine : `configs/prospective_observatory_v1.json`. Le document décrit
ce contrat ; le runtime doit refuser une divergence.

## Tolérance

La tolérance opérationnelle gelée est d’une heure de part et d’autre de
l’échéance nominale. Elle garantit qu’une exécution horaire couvre toute
minute de kickoff sans polling intermédiaire. Pour les fenêtres proches du
match, le cutoff reste strictement borné à `kickoff_at - 1 µs`. Une exécution
horaire sélectionne les fixtures dues ; elle ne transforme pas le scheduler
GitHub en boucle.

## Fixtures et statut général

```text
J-21
J-14
J-7
J-3
J-1
H-6
H-2
H-1
H-0:30
```

## Blessures et disponibilités

```text
J-7
J-3
J-1
H-6
H-2
H-1
```

## Joueurs et squads

```text
J-7
J-3
J-1
```

## Lineups et formations

```text
H-2
H-1
H-0:45
H-0:30
H-0:15
```

## Cotes

```text
J-7
J-3
J-1
H-6
H-2
H-1
H-0:30
```

Marchés initiaux : `1X2` et `OVER_UNDER_2_5`. Aucun marché joueur n’appartient
au Jalon 12.

## Classification

- avant l’ouverture : `NOT_DUE` ;
- entre ouverture et cutoff : `DUE` ;
- réponse valide durable : `CAPTURED` ;
- réponse valide vide : `CAPTURED_EMPTY` ;
- problème temporaire dans la fenêtre : `RETRY_PENDING` ;
- fin de fenêtre sans capture admissible : `MISSED_WINDOW`.

Une fenêtre ne peut être capturée qu’une fois par identité métier et hash. Un
second passage identique est un replay, pas une nouvelle observation.

## Horizon

Le registre résout les trente prochains jours, au plus trois journées par
compétition, avec phase et saison vérifiées. Les matchs annulés et les
kickoffs non fiables sont exclus ou restent explicitement non planifiables.
Les équipes et saisons ne sont pas codées en dur hors registre.

## Exécution sûre

Avant chaque lot, publier fixtures suivies, fenêtres prévues, fenêtres dues,
coût maximum et réserves. `windows_due=0` est un succès sans appel fournisseur.
Une fenêtre passée n’est jamais reconstruite pour améliorer artificiellement
la couverture.
