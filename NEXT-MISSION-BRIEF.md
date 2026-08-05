# Prochaine mission — P0 Coverage Evidence Ladder V1

## État d'entrée prouvé

- Council V3.1 minimal fusionné par merge commit ;
- PR #28 compactée, auditée et fusionnée par merge commit ;
- CI du nouveau `main@96bcc2d56f1b68a011f1efa11022ebd4b8713208` verte ;
- branche dédiée `codex/p0-coverage-evidence-ladder-v1` et PR draft #30 ;
- checkout d'accueil protégé inchangé ;
- P0 défini par `5 compétitions × 6 saisons × 16 familles = 480 cellules` ;
- aucune fermeture empirique héritée : `0/480`.

## Contrat d'échelle corrigé

L'ordre du domaine est :

```text
E0 → E1A → E1B → E2 → E3A → E3B → E4
```

L'ordre du Council reste :

```text
E1 → E2 → E3A → E3B → E4
```

E1A et E1B sont les deux composantes de Council E1. E1A seule produit
`PASS_AND_HOLD`; seule la preuve conjointe E1A + E1B peut autoriser E1 → E2.
Le legacy E2 à 50 fixtures est incompatible avec le nouveau E2 à 100 fixtures.
Toute écriture legacy ou tout label ambigu `E1`/`E3` est rejeté.

## Autorité et sources gelées

Le mapping v2 n'accorde aucune autorité d'exécution. Avant tout calcul, utiliser :

- le manifeste Council immuable à huit champs ;
- la configuration source qui épingle l'inventaire R2 signé
  `87326eba00976c8cdd00c68e7d24b98c1ccd4f109b38681228f527bcb273e28d` ;
- le manifeste de sélection du niveau, publié et committé avant `measure`.

L'accès R2 est limité à un `GET` de l'inventaire exact, puis aux seules clés de
reçu/payload présentes dans cet inventaire vérifié. Aucun LIST raw ou dérivé,
HEAD, PUT, DELETE, COPY ou multipart n'est autorisé. L'artefact GitHub de
récupération est un miroir non autoritatif ; R2 et Git conservent la preuve.

Par défaut et pendant toute l'échelle :

```text
API_FOOTBALL_CALLS_ALLOWED=0
R2_WRITES_ALLOWED=0
R2_DELETES_ALLOWED=0
REMOTE_SQL_READS_ALLOWED=0
REMOTE_SQL_WRITES_ALLOWED=0
ODDS_API_CREDITS_ALLOWED=0
DEPLOYMENTS_ALLOWED=0
PURCHASES_ALLOWED=0
REAL_BETS=false
```

## Niveaux

### E1A — canari mono compétition-saison

Sélectionner exactement 10 fixtures réelles du meilleur couple P0, triées par
`kickoff_utc`, puis `fixture_id`. Exiger identités explicites, reçu, hashes,
provenance, zéro ambiguïté et deux générations scientifiques identiques. Mesurer
les sept compteurs et les trois taux séparés. Fermer `0/480` cellule.

### E1B — canari cinq ligues

Sélectionner exactement 2 fixtures par compétition, soit 10 fixtures. Interdire
collision d'identité, mapping positionnel, divergence de grain et fuite client.
Fermer `0/480`. E1A + E1B réussis prouvent Council E1.

### E2 — 100 fixtures

Sélectionner exactement 20 fixtures par compétition. Préférer une saison commune,
sinon figer la meilleure saison par compétition. Éprouver les 16 familles, les
grains, doublons, nulls, vides valides et agrégations pondérées. Fermer `0/480`.

### E3A — une compétition-saison complète

Traiter le meilleur scope complet, avec census exact et dénominateurs prouvés.
Une cellule n'est fermée que si scope, reçu, hash, grain et compteurs sont
complets ; sinon elle reste explicitement partielle. Plafond : 16 cellules.

### E3B — une saison sur cinq ligues

Traiter la meilleure saison commune sur Ligue 1, Premier League, Liga,
Bundesliga et Serie A. Aucune moyenne simple et aucun mélange de saison.
Plafond de scope : 80 cellules.

### E4 — P0 complet

Traiter uniquement P0 2020–2025. Partitionner par compétition-saison puis par
groupe de familles, au plus 120 jobs. Cible ≤10 minutes, maximum ≤15 minutes,
checkpoint ≤5 minutes. Publier le reçu compact de 480 cellules, les taux pondérés,
les gates et les coûts observés. Les cellules non prouvées restent partielles.

## Protocole par niveau

```text
freeze source/selection
→ vérifier et committer le manifeste
→ measure sur ce hash exact
→ test du niveau + suite du domaine
→ revue indépendante
→ décision Council + checkpoint
→ commit durable
→ passage automatique si les gates passent
```

Aucune validation utilisateur intermédiaire. Après deux interruptions similaires,
changer d'architecture. Une troisième tentative identité inchangée produit
`FAIL_AND_STOP`.

## Après E4

Recalculer séparément les huit gates fonctionnels, les verdicts de couverture et
les 486 propriétés. Météo et pied fort restent `BLOCKED_BY_SOURCE` sans falsifier
P0. Ouvrir l'hypergraphe seulement si un sous-espace de propriétés possède une
preuve suffisante : masques atomiques, propriétés seules, paires compatibles,
puis triples plafonnés à 5 000 000. Aucune profondeur 4+ sans benchmark favorable.

Le Desk peut recevoir un flux compact et sanitizé. Aucune refonte visuelle profonde
avant la revue de David ; fixture IDs, endpoints, payloads, reçus et secrets ne
doivent jamais entrer dans le bundle client.
