# Protocole prospectif des hypothèses

## Gel initial

Le gel V1 est fixé au `2026-07-29T13:30:00Z` sur le commit de base
`0057e1caf57bd4d6084ab456f7ee386fff728c2c`. Il porte sur les trois premières
règles J10 :

- `J10-M001` ;
- `J10-M002` ;
- `J10-M003`.

Ce choix est historique et exploratoire. Il ne transforme aucune règle en
modèle validé. Les métriques J10 sont conservées avec leurs hashes et leurs
contrôles.

## Contrat de prix

La source prévue est The Odds API, sans appel au moment du gel.

- contrat primaire : fenêtre `NEAR_KICKOFF` ;
- contrat secondaire : fenêtre `H-2` ;
- cote, marge, sélection, ligue et cutoff doivent respecter les bornes gelées ;
- une donnée manquante, tardive, incohérente ou hors contrat produit une
  observation non éligible, jamais une substitution silencieuse.

## États d'observation

Les statuts persistés sont `ELIGIBLE_FROZEN`, `NOT_ELIGIBLE`,
`REJECTED_MISSING_PRICE`, `REJECTED_LATE`, `VOID` et `SETTLED`. Le motif
précise notamment une cote hors bande, une marge bloquée, une compétition ou
sélection incompatible, un cutoff inconnu ou une fixture reportée. Chaque
décision est déterministe à partir du contrat gelé et des données référencées.

## Règlement et corrections

Un règlement est idempotent pour un couple observation/résultat. Une correction
de résultat crée un nouvel événement lié au précédent ; elle ne réécrit pas
l'historique. Les issues autorisées couvrent gain, perte, nul/push et void selon
le marché.

## Checkpoints

Les revues prospectives sont prévues à 30 observations, 80 observations et en
fin de saison. Elles comparent les performances au contrat préenregistré,
documentent les contrôles négatifs et l'incertitude, puis soumettent toute
promotion éventuelle à une validation humaine explicite.

## Verrous

Le protocole ne déclenche ni appel fournisseur, ni prédiction de production, ni
pari, ni publication sociale, ni entraînement réel. Tous les verrous existants
restent prioritaires.
