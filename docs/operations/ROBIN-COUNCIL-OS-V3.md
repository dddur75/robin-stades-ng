# Robin Council OS V3.1 minimal

## Finalité

Robin Council transforme une intention en livraison par une chaîne vérifiable :

```text
intention → faits vérifiés → plus petite expérience décisive
→ décision de niveau → réalisation externe → recette → livraison
```

Le Council est une politique de contrôle. Il autorise une mission, valide une
transition et enregistre une décision. Il ne planifie, ne lance et ne répare
aucune exécution.

Le registre des rôles est `configs/agents/agent-registry-v3.json`. Les équipes
sont activées uniquement par mission selon
`configs/agents/mission-activation-matrix-v3.json`.

## Autorité et écriture

C0 nomme un rédacteur unique par worktree. Les autres agents lisent, testent et
objectent sans modifier le worktree. L'auteur d'un composant ne peut ni fermer
seul une objection ni lui attribuer seul son score. Un fait est accepté par sa
preuve, jamais par une majorité.

Un veto C1 contient : code, risque exact, preuve manquante, plus petit test
décisif, plus petit correctif, coût, condition de reprise et responsable. Un
veto critique ouvert bloque toute progression.

## Les cinq fonctions V3.1

### 1. Autoriser une mission

Le manifeste est immuable et contient exactement : `mission_id`,
`authorized_stages`, `maximum_stage`, `external_effects`, `compute_budget`,
`time_budget`, `source_hash` et `expires_at`. Il ne peut ni s'étendre après
création, ni contourner la matrice d'activation ou les verrous de sécurité.

### 2. Représenter une décision

Les valeurs uniques sont `PASS_AND_SCALE`, `PASS_AND_HOLD`,
`FAIL_AND_REDESIGN`, `FAIL_AND_STOP` et `BLOCKED_EXTERNAL_ACTION`.

### 3. Valider une transition

La chaîne est `E1 → E2 → E3A → E3B → E4`. Une transition est valide uniquement
si l'étape courante est prouvée, la suivante est immédiate, autorisée et sous le
plafond, les critères et budgets sont satisfaits, le manifeste n'est pas expiré,
aucun veto critique n'est ouvert et aucun effet externe interdit n'est demandé.

`PASS_AND_SCALE` ouvre exactement un niveau. Il ne crée aucune autorité et ne
relève jamais `maximum_stage`. Au plafond, le résultat est `PASS_AND_HOLD`. Une
source obligatoire absente donne `FAIL_AND_STOP`; un effet externe interdit donne
`BLOCKED_EXTERNAL_ACTION`.

### 4. Appliquer la règle des deux échecs

Le premier échec similaire appelle le plus petit correctif et conserve le
niveau. Le deuxième produit `FAIL_AND_REDESIGN` et ramène à E1. Une troisième
tentative inchangée est interdite et produit `FAIL_AND_STOP`.

### 5. Enregistrer les faits de contrôle

Le journal append-only contient seulement : mission autorisée, étape commencée,
étape terminée, décision, échec, veto et redesign. Leur représentation JSON est
canonique; chaque record porte un hash SHA-256 déterministe et le hash précédent.
Le journal prouve la chaîne de contrôle locale, pas l'exécution du workload.

## Frontière d'exécution

Le Council ne remplace ni GitHub Actions, ni R2, ni Git, ni Codex. Il ne coupe
pas le réseau, ne filtre pas les secrets, ne crée aucun sandbox, et ne prétend pas
faire de transaction distribuée. L'exécuteur reste extérieur à cette politique
et doit fournir les preuves de domaine attendues.

Appels fournisseurs, écritures R2 ou SQL, déploiements, achats, promotions,
publications et autres effets externes ou irréversibles restent `DEFAULT_DENY`.
Une éventuelle autorisation séparée relève de la matrice d'activation et ne peut
jamais être déduite d'un `PASS_AND_SCALE`.

## Capacités différées

Sont explicitement `FUTURE_DESIGN_NOT_IMPLEMENTED` :

- ordonnanceur ou moteur d'exécution;
- transactions distribuées et protocole transactionnel de crash;
- rotation d'autorité complexe ou contrôleurs concurrents;
- récupération d'authority race et quarantaine post-commit;
- reconstruction complète des grants et bindings multiples de preuves;
- remplacement de GitHub Actions, R2, Git ou de l'orchestrateur Codex.

Ces sujets ne peuvent pas être réintroduits par une red-team V3.1. Une objection
finale demande un correctif local ou signale un blocage critique.

## Preuves et lignée

Chaque affirmation importante possède un `claim_id` dans le graphe de preuves.
La lignée sépare :

- `execution_id`, propre à une exécution;
- `scientific_lineage_id`, stable entre reprises compatibles;
- `dataset_lineage_id`, lié au contenu et à ses hashes.

Les manifests, receipts et datasets compatibles sont réutilisés sans replay
général. Un run ou un artefact GitHub ne peut pas être l'unique preuve durable.
Le Council consomme des références de preuve; il n'implémente pas un système de
bindings multiples.

## Clés de livraison

| Domaine | Validateurs indépendants |
|---|---|
| données | DP6 + C2 |
| plateforme | DP5 + A2 |
| produit couverture | C3 + UX3 + UX6 |
| science couverture | C2 + RP2 + A1 |
| hypothèse/backtest | C2 + RP8/RP9 + A1 |
| interface | C3 + UX6 + A3 |

Une phase est `READY` avec un score au moins égal à 95/100, aucune objection
critique, aucune preuve obligatoire manquante et aucun verrou de sécurité
affaibli. Sinon, `PARTIAL` est un verdict valide et obligatoire.

## Livrables de contrôle

- décisions : `reports/council/decision-ledger.jsonl`;
- rapports d'agents : `configs/agents/agent-report-schema-v3.json`;
- politique minimale : `configs/experiments/scale-policy-v3.json`;
- preuves : `reports/evidence/evidence-graph.json`;
- capacités : `reports/platform/platform-audit.json`;
- dérive de périmètre : `reports/council/v31-scope-drift-review.json`.

Le code de production V3.1 reste sous 1 000 lignes, ses tests sous 2 000 lignes,
ses schémas spécifiques sous 500 lignes, sans dépendance ni service externe
nouveau. La simplification exécute des tests ciblés et une seule suite complète
avant fusion.

## Sécurité immuable

```text
STORAGE_PAUSED=true
P3_P4_PAUSED=true
PRODUCTION_LOCKED=true
REAL_BETS=false
NO_BET_DEFAULT=true
PROMOTION_LOCKED=true
SOCIAL_PUBLISHING_ENABLED=false
DEMO_MODE_ENABLED=false
```

Aucun achat, secret exposé, pari réel, promotion, publication sociale, suppression
R2 ou écriture destructive n'est autorisé par le Council.
