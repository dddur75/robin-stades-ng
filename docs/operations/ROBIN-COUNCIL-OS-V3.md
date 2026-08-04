# Robin Council OS V3

## Finalité

Robin Council transforme une intention en livraison par une chaîne vérifiable :

```text
intention → conseil spécialisé → faits vérifiés → plus petite expérience décisive
→ montée en charge conditionnelle → réalisation → red-team → recette → livraison
```

Le registre des rôles est `configs/agents/agent-registry-v3.json`. Le conseil
central C0–C4 reste responsable de la finalité, de la qualité expérimentale, de
la science, du produit et des risques. Les équipes Data Platform, Recherche,
Produit/UX et Audit sont activées uniquement par mission selon
`configs/agents/mission-activation-matrix-v3.json`.

## Autorité et écriture

C0 nomme un rédacteur unique par worktree. Cette nomination est enregistrée dans
le ledger avant le premier commit. Les autres agents lisent, testent et objectent
sans modifier le worktree. L'auteur d'un composant ne peut ni fermer seul une
objection ni lui attribuer seul son score.

Un veto C1 contient obligatoirement : risque exact, preuve manquante, plus petit
test suffisant, coût et condition de déblocage. Un fait est accepté par sa preuve,
jamais par une majorité.

## Boucle de décision

Chaque phase suit dix étapes : observer, formaliser, tester au plus petit niveau,
mesurer, contredire, corriger, décider la montée en charge, réaliser, recetter et
livrer. Le passage E(n) → E(n+1) exige une décision `SCALE_APPROVED` dans le
ledger. Deux échecs de même classe imposent `REDESIGN_REQUIRED`.

## Preuves et lignée

Chaque affirmation importante possède un `claim_id` dans le graphe de preuves.
La lignée sépare :

- `execution_id`, propre à une exécution ;
- `scientific_lineage_id`, stable entre reprises compatibles ;
- `dataset_lineage_id`, lié au contenu et à ses hashes.

Un run ou artefact GitHub ne peut pas être l'unique preuve durable. Les receipts
et manifests R2 compatibles sont réutilisés sans replay général.

## Clés de livraison

| Domaine | Validateurs indépendants |
|---|---|
| données | DP6 + C2 |
| plateforme | DP5 + A2 |
| hypothèse/backtest | C2 + RP8/RP9 + A1 |
| interface | C3 + UX6 + A3 |

Une phase est `READY` avec un score au moins égal à 92/100, aucune objection
critique, aucune preuve obligatoire manquante et aucun verrou de sécurité affaibli.

Une mission Cockpit doit en plus tracer le parcours non technique en français,
clavier, lecteur d'écran manuel, zoom 200 %, 360/375/390/430 px, console et
`pageerror`, liens, mouvement réduit, `fr-FR`/préparation i18n, SSR/hydratation et
états vides. La PR de gouvernance ne touche aucune interface ni aucun déploiement :
ces contrôles y sont `NOT_APPLICABLE`, mais ils bloquent toute future interface
`READY`.

## Livrables de contrôle

- décisions : `reports/council/decision-ledger.jsonl` ;
- rapports d'agents : schéma `configs/agents/agent-report-schema-v3.json` ;
- preuves : `reports/evidence/evidence-graph.json` ;
- capacités : `reports/platform/platform-audit.json` ;
- échelle : `configs/experiments/scale-policy-v3.json`.

La scorecard et le relevé de validation gouvernance complètent cette liste dans
`reports/council/`. La première matérialise le seuil 92/100 imposé; le second
donne aux claims de test un artefact durable au lieu de dépendre d'une sortie de
terminal ou du corps de PR.

Le verdict `PARTIAL` est un résultat valide et obligatoire quand une source, une
limite, un budget ou un risque scientifique empêche une conclusion défendable.
