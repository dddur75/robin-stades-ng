# ROBIN DES STADES 2.0
# E3A REAL COMPETITION-SEASON V1
# REVUE ET FUSION DU TARGETED FIX PACK
# PROGRESSION PAR CAPACITÉ
# ARRÊT AVANT LES MILLIONS DE TRIPLES

## 0. Configuration

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
BRANCHE À REVOIR = codex/e2-targeted-fixes-e3a-launch-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Commencer par la revue et la fusion de la PR `E2 Targeted Fixes and E3A Launch
V1`. Vérifier le head, les deux GET de diagnostic, les rapports sanitisés, le
Golden Pack Calendar, la CI et le nouveau `main` avant toute acquisition E3A.

## 1. Preuves immuables

```text
E1A = 3036 = 2681 + 206 + 149
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
E2 fixtures = 100
E2 logical GET = 161
E2 bytes = 6434224
E2 replay = BYTE_IDENTICAL
fixture 1208603 = PROVIDER_INCONSISTENCY
PLAYER_STATISTICS = E2_MEASURED_PARTIAL
CALENDAR = CALENDAR_STRICT_ASOF_MECHANICALLY_VALIDATED
E3A executed = false
E3B executed = false
masks built = false
```

Ne lancer ni E1A ni une troisième architecture. Ne jamais convertir `UNKNOWN`
en zéro, faux, blessure ou suspension. Le contrat autoritatif reste
`configs/data/capability-scoped-evidence-ladder-v2.json`.

## 2. Budgets à geler avant exécution

```text
r2_read_budget = 10000 GET
r2_write_budget = 0
api_football_budget = 0
sql_read_budget = 0
sql_write_budget = 0
odds_budget = 0
TRIPLE_SEARCH_LOCKED = true
```

Chaque accès R2 est exact-key, borné, précédé d'une sélection immuable et d'une
décision append-only. LIST, HEAD, écriture, suppression, fournisseur, Odds et SQL
distant restent à zéro. Deux tentatives techniques maximum par périmètre.

## 3. E3A

Après fusion et `main` vert, geler une compétition-saison canonique. Exécuter
E3A uniquement pour :

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
DISCIPLINE_GENERIC
CALENDAR
```

`PLAYER_STATISTICS` reste exclue jusqu'à acceptation scientifique explicite de
`missing_player_stat_row = UNKNOWN` sur le périmètre gelé. Calendar doit utiliser
le contrat strict as-of et ne peut être promue sur sa seule preuve synthétique.
Lineup et Formation restent post-match sans source as-of distincte.

Mesurer par capacité : grain, expected, received, empty-valid, UNKNOWN, invalid,
doublons, couverture pondérée, temporalité, dépendances, stabilité et coût.
Rejouer deux fois hors réseau et exiger des octets identiques sans GET additionnel.

## 4. E3B conditionnel

Exécuter E3B sur cinq ligues uniquement si E3A passe pour la capacité concernée,
les coûts restent dans le manifeste et aucun veto critique n'est ouvert. Un échec
local ne bloque que ses dépendants déclarés.

## 5. Après les gates

Seulement après E3A/E3B admissibles : recenser les champs non mappés, geler le
registre canonique des tags, benchmarker les représentations de masques,
construire les masques atomiques, tester les propriétés seules puis les paires
compatibles.

Ne jamais lancer les millions de triples avant :

```text
masques validés
prix historiques admissibles
support minimal défini
folds temporels disponibles
contrat statistique gelé
```

## 6. Interdictions

Pas de fournisseur, Odds, SQL distant, écriture R2, déploiement, publication,
pari réel ou promotion. Ne pas lancer E4, hypergraphe, backtest massif,
entraînement ni millions de triples. Préserver toutes les preuves historiques.

## 7. Livrables et arrêt

Publier rapports E3A, puis E3B seulement si autorisé, coûts, replay, gates par
capacité, recensement, registre et benchmarks réalisés. Laisser toute mission
de triples verrouillée. Rendre `PASS_AND_HOLD` ou `PARTIAL_AND_HOLD` et laisser
les worktrees propres.
