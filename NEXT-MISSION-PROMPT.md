# ROBIN DES STADES 2.0
# E2 TARGETED FIXES AND E3A V1
# REVUE ET FUSION DE LA PR #34
# PROGRESSION PAR CAPACITÉ UNIQUEMENT
# ARRÊT AVANT E3B ET AVANT LES MASQUES

---

# 0. CONFIGURATION

```text
OUTIL = Codex
DÉPÔT = dddur75/robin-stades-ng
BRANCHE D’ACCUEIL VISIBLE = codex/hypothesis-universe-experience-v1
PR À REVOIR = #34
BRANCHE À REVOIR = codex/p0-e2-capability-sample-v1
MODÈLE = GPT-5.6 Sol
RAISONNEMENT = Très élevé
ACCÈS = Complet
DURÉE = 20 à 50 heures utiles
```

Cette mission commence par la revue des preuves E2 et les deux correctifs ciblés.
Elle ne doit pas réexécuter E2 globalement si les hashes et la CI restent valides.

---

# 1. OBJECTIF UNIQUE

1. résoudre l'état réel de la PR #34 et auditer ses preuves compactes ;
2. fusionner la PR #34 par merge commit si le head exact et la CI sont sains ;
3. vérifier la CI du nouveau `main` ;
4. traiter séparément les gaps `PLAYER_STATISTICS` et `CALENDAR` ;
5. geler un manifeste E3A pour les seules capacités admissibles ;
6. exécuter E3A de façon bornée sur une compétition-saison ;
7. recalculer les gates par capacité, les coûts et le replay ;
8. préparer E3B sans l'exécuter ;
9. s'arrêter avant E3B et avant tout masque.

Verdict : `PASS_AND_HOLD` ou `PARTIAL_AND_HOLD`.

---

# 2. PREUVES D'ENTRÉE IMMUABLES

```text
E2 selection hash = 5f0ad80ce5ae43b4b4010c0e06dff8828330bcd60282bf940c9f1e87e601286b
E2 run = 31192408221
E2 logical GET = 161
E2 bytes = 6434224
E2 replay = BYTE_IDENTICAL
E3A executed = false
masks built = false

E1A observations = 3036
injuries confirmed = 2681
suspensions confirmed = 206
ABSENCE_CAUSE_UNKNOWN = 149
2681 + 206 + 149 = 3036
ABSENCE_CAUSE_EXACT = STOPPED_LOCAL_CAMPAIGN
```

Ne pas rouvrir E1A, créer une Architecture 3, projeter les 149 inconnues par
ligue ou convertir `UNKNOWN` en zéro, blessure ou suspension.

---

# 3. CHECKOUT PROTÉGÉ ET GIT

Le checkout visible est une porte d'entrée uniquement. Ne jamais y modifier,
indexer, committer, pousser, fusionner, rebaser, nettoyer ou changer de branche.
Utiliser des worktrees dédiés.

La PR #34 doit rester la source E2 autoritative. La fusion n'est permise qu'après
contrôle du head, des claims, des hashes, des tests, de la CI, du diff et de
l'absence de payload brut, secret, chemin absolu ou fichier temporaire. Conserver
la branche distante et attendre le vert du merge commit sur `main`.

---

# 4. RÉSULTAT E2 À PRÉSERVER

Candidates E3A :

```text
TEAM
PLAYER
LINEUP
FORMATION
EVENTS
TEAM_STATISTICS
DISCIPLINE_GENERIC
```

Correctifs ciblés :

```text
PLAYER_STATISTICS = E2_MEASURED_PARTIAL
CALENDAR = E3A_TARGETED_FIX_REQUIRED
```

`PLAYER_STATISTICS` conserve exactement 4 208 reçues / 4 209 attendues,
1 `UNKNOWN` et 1 invalide tant qu'une preuve distincte ne résout pas la divergence.
La seule partition affectée est Liga, nouvelle fixture `1208603`, strate 6,
objet signé `2a106520004fcd3945b821db8130f2a671ad8ef7d17b83c8077fc495338c7135`.

`CALENDAR` a 100/100 objets présents mais ne prouve pas encore l'information
disponible avant match : `FINAL_STATE_NOT_KNOWN_AS_OF`.

---

# 5. CORRECTIFS E2 CIBLÉS

## PLAYER_STATISTICS

- partir du grain joueur-fixture et des identités provider prouvées ;
- distinguer absence, valeur inconnue, identité hors grain et doublon ;
- ne jamais attribuer la statistique au joueur le plus proche ou par position ;
- ne relire que les clés exactes déjà signées si une relecture est indispensable ;
- produire un gap report et un test adversarial avant toute modification de statut.

## CALENDAR

- définir une source et un timestamp `KNOWN_AS_OF` ;
- séparer horaire planifié, changement connu, kickoff réel et état final ;
- interdire toute fuite post-match dans une propriété pré-match ;
- tester report, annulation, changement d'horaire et absence de snapshot historique.

Chaque correctif progresse indépendamment. Un échec local ne bloque que ses
dépendants déclarés.

---

# 6. GATE AVANT TOUTE LECTURE DISTANTE

Créer avant lecture : manifeste de mission, sélection exacte, budgets, stop
conditions et décision append-only. Exiger une revue DP6, C2 et DP5.

```text
API_FOOTBALL_CALLS_ALLOWED = 0
ODDS_CREDITS_ALLOWED = 0
REMOTE_SQL_ALLOWED = 0
R2_LIST_ALLOWED = 0
R2_HEAD_ALLOWED = 0
R2_WRITES_ALLOWED = 0
R2_DELETES_ALLOWED = 0
DEPLOYMENT_ALLOWED = 0
PUBLICATION_ALLOWED = 0
REAL_BETS = false
PROMOTION_LOCKED = true
```

Les GET R2 sont exact-key uniquement et bornés par un nouveau manifeste. Aucun
scan de préfixe, fallback, clé dynamique ou augmentation automatique de budget.

---

# 7. E3A BORNÉ

Après fusion E2, nouveau `main` vert et corrections admissibles, sélectionner
une compétition-saison canonique. Geler la sélection et les seuils avant lecture.

Pour chaque capacité autorisée, mesurer : grain, expected, received, empty-valid,
UNKNOWN, invalid, doublons, couverture pondérée, intégrité de normalisation,
temporalité, dépendances, stabilité temporelle et coût.

`LINEUP` et `FORMATION` doivent rester explicitement post-match tant qu'aucune
preuve as-of distincte n'existe. `EVENTS` et `DISCIPLINE_GENERIC` ne reçoivent
pas de dénominateur d'occurrences inventé.

E3A ne peut pas déclarer une readiness globale. Publier une décision par capacité.

---

# 8. REPLAY ET VALIDATION

Après acquisition, conserver les payloads uniquement dans l'espace temporaire du
job. Agréger et régénérer deux fois hors réseau ; exiger la byte-identité et zéro
GET supplémentaire.

Valider : sélection, grains, dénominateurs, pondération, UNKNOWN, temporalité,
dépendances, comparaison E2/E3A, coûts, replay, dashboard data-only, Ruff, mypy
strict, JSON/YAML, UTF-8, secrets, `git diff --check`, tests de domaine et CI
ciblée du head exact.

Maximum deux tentatives techniques au même périmètre.

---

# 9. INTERDICTIONS

Ne pas exécuter E3B, E4, masque atomique, propriété, paire, triple, hypergraphe,
backtest, entraînement, modèle prédictif, collecte fournisseur, Odds, SQL distant,
écriture R2, déploiement, publication, pari ou promotion.

Ne pas lancer les millions de triples avant :

```text
masques validés
prix historiques admissibles
support minimal défini
folds temporels disponibles
contrat statistique gelé
```

---

# 10. ARRÊT OBLIGATOIRE

Après E3A : publier rapports, coûts, replay, matrice de progression locale et
handoff E3B. Ne lancer ni E3B ni les masques. Laisser le worktree propre, la PR
de la mission en brouillon et toutes les actions interdites à zéro.
