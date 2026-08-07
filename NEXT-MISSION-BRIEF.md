# Next Mission Brief — P0 E2 Hundred-Fixture Capability Evidence V1

## Configuration

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
BRANCHE À REVOIR = codex/p0-e1b-five-league-capability-canary-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Cette mission est préparée mais n’a pas été exécutée.

## Point de départ

1. résoudre l’état réel de la PR brouillon E1B sur GitHub ;
2. vérifier ses rapports, son head exact et sa CI ;
3. fusionner par merge commit si elle reste saine ;
4. vérifier la CI de `main` ;
5. créer un worktree E2 depuis le nouveau `origin/main`.

Autorité E1B : sélection 2024 de dix fixtures, hash
`8e3ef9e5e44ef26ef4fd37d884b3290504f2b167b1fceeec669e0ed8684deb22`,
run vert `31177349967`, verdict `PASS_AND_HOLD`.

Contrat autoritatif :
`configs/data/capability-scoped-evidence-ladder-v2.json`.

## Objectif

Exécuter E2 sur 100 fixtures réelles pour les seules capacités candidates :

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
PLAYER_STATISTICS
DISCIPLINE_GENERIC
CALENDAR
```

Recalculer les gates par capacité avec grains, dénominateurs pondérés,
temporalité, UNKNOWN, provenance, coûts, replay et décisions de progression.

## Bornes

- `ABSENCE_CAUSE_EXACT` reste `STOPPED_LOCAL_CAMPAIGN` ;
- E1A reste gelée : ne pas la rouvrir et ne créer aucune troisième architecture ;
- TEAM_FORM, PLAYER_FORM, STARTER_BASELINE, FATIGUE et STANDINGS ne progressent
  pas sans correctif ciblé et preuve distincte ;
- aucune readiness n’est héritée du canari E1B ;
- aucun appel API-Football, odds, SQL, déploiement, publication ou pari ;
- R2 uniquement par clés exactes gelées, sans LIST, HEAD ou écriture implicite ;
- aucune E3A/E3B, masque, propriété, paire ou triple avant le verdict E2 ;
- maximum deux tentatives techniques au même périmètre.

## Fin attendue

Produire les preuves E2 sur 100 fixtures, une matrice de progression locale et
un `PASS_AND_HOLD` ou `PARTIAL_AND_HOLD`. La mission suivante seulement pourra
envisager E3A pour les capacités dont E2 autorise explicitement l’échelle.
