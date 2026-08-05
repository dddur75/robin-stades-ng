# Mission compilée — P0 Coverage Evidence Ladder V1

Tu es Codex dans Robin des Stades. Exécute automatiquement E1A, E1B, E2, E3A,
E3B puis E4 dans la PR draft `P0 Coverage Evidence Ladder V1 — E1 à E4`.
Ne demande aucune validation utilisateur entre les niveaux.

## 1. Préconditions immuables

1. Rester dans le worktree de `codex/p0-coverage-evidence-ladder-v1`.
2. Ne jamais modifier le checkout d'accueil protégé.
3. Lire `AGENTS.md`, la matrice d'activation, le ledger, le graphe de preuves,
   le mapping v2, la source P0, le manifeste Council et le catalogue des grains.
4. Vérifier les hashes LF de tous les contrats épinglés.
5. Refuser tout calcul si le manifeste Council est expiré, si son source hash
   diverge, si un veto critique est ouvert ou si le budget est dépassé.

## 2. Autorisation

Le mapping n'autorise ni workload ni scale. Le manifeste Council contient
exactement huit champs et autorise seulement les étapes Council E1 à E4. E1A et
E1B ne sont jamais ajoutés à l'enum Council : ils prouvent conjointement E1.

Seuls les effets suivants peuvent être demandés avec preuve séparée de matrice :

```text
github_actions_execute_read_only
r2_read_existing_immutable_evidence
```

Tous les appels fournisseur, écritures/suppressions R2, SQL distant,
déploiements, achats, paris, promotions et publications restent interdits.
N'utilise ni les workflows 70/71, ni les runners harvest/replay qui écrivent un
sentinel. Étends seulement le workflow 81 existant avec une surface GET-only.

## 3. Source R2

Charger l'inventaire exact épinglé par la configuration source. Valider sa
signature, ses compteurs, segments, objets, dimensions, hashes, tailles et clés.
Après cette validation, autoriser uniquement les clés `receipt_key` et
`payload_key` présentes dans l'inventaire. Le lecteur ne possède aucune méthode
LIST, PUT, DELETE, COPY ou multipart et ne monte ni clé API-Football ni secret SQL.

L'inventaire prouve l'appartenance et la provenance des objets, pas les
dénominateurs. Ses champs `rows_received` ne sont jamais utilisés comme compteurs
empiriques. Les six familles raw peuvent projeter seize familles normalisées ;
aucune fermeture n'est inférée du seul label raw.

## 4. Identités et mesures

Utiliser `p0-evidence-identity-registry-v1` : IDs fournisseur positifs explicites,
identités compétition/saison contrôlées, clés sémantiques non positionnelles,
partition d'absence `SUSPENSION / INJURY / UNCLASSIFIABLE`. Toute ambiguïté,
collision ou dépendance à une position de tableau échoue fermée.

Pour chaque unité applicable, conserver :

```text
expected
received
empty_valid
invalid
unclassifiable
exact_duplicates
contradictory_duplicates
```

Calculer séparément `scope_completion`, `normalization_integrity` et
`content_presence`. Un taux global vaut uniquement somme des numérateurs divisée
par somme des dénominateurs. `UNKNOWN` n'est jamais zéro et `EMPTY_VALID` n'est
jamais manquant.

## 5. Boucle de niveau

Pour chaque niveau :

1. `freeze` sélectionne le scope déterministement et publie seulement le manifeste.
2. Télécharger, vérifier et committer ce manifeste avant tout calcul scientifique.
3. `measure` refuse tout autre hash et lit seulement les objets listés.
4. Générer deux fois la section scientifique et exiger le même hash.
5. Produire reçu, compteurs, taux, gate, coûts, checkpoint et flux client sanitizé.
6. Exécuter le test du niveau, la suite du domaine et la revue indépendante.
7. Ajouter la décision Council et le graphe append-only avant le commit durable.
8. Passer automatiquement au niveau suivant lorsque les gates passent.

Scopes exacts :

```text
E1A = 10 fixtures, une compétition-saison, tri kickoff_utc puis fixture_id
E1B = 2 fixtures × 5 compétitions = 10
E2  = 20 fixtures × 5 compétitions = 100
E3A = une compétition-saison complète, au plus 16 cellules
E3B = une saison commune × 5 compétitions, au plus 80 cellules
E4  = 5 × 6 × 16 = 480 cellules
```

E1A, E1B et E2 ferment toujours `0/480`. E1A réussie donne Council
`PASS_AND_HOLD`. E1A + E1B réussies peuvent donner E1 → E2. E4 est terminal :
son succès donne `PASS_AND_HOLD` au plafond, jamais une transition inventée.

## 6. Gates fail-closed

- E1A : 10/10, identités 100 % prouvées, zéro ambiguïté ou contradiction,
  déterminisme double.
- E1B : 2×5, zéro collision, position ou divergence de grain, zéro fuite client.
- E2 : 100/100, zéro identité devinée/hash divergent/scope incohérent,
  mémoire et temps sous budget.
- E3A : census exact, fixtures distinctes, reçus et dénominateurs prouvés,
  cellules fermées ou explicitement partielles.
- E3B : cinq ligues, même saison, pondération correcte, checkpoints réutilisables.
- E4 : 480 résultats exacts ou partiels explicites, jobs ≤15 min et aucune
  matrice >256.

Si la source manque réellement, arrêter `FAIL_AND_STOP` ou `PARTIAL`. Ne pas
déclencher de secours fournisseur en E1. Une éventuelle récupération de census
exige un manifeste C0/C1/C4 séparé et le plafond absolu de 100 appels.

## 7. Après E4

Recalculer les huit gates, les verdicts distincts et les 486 propriétés sans
modifier les seuils. Ouvrir l'hypergraphe uniquement si des propriétés sont
réellement exploitables : masques, propriétés, paires exhaustives, triples
sélectionnés plafonnés à 5 000 000. Ne pas lancer profondeur 4+.

Ne pas refaire le dashboard. Autoriser seulement données, navigation cassée,
résultats E1–E4, confidentialité et contrat du futur cockpit. Conserver
`DASHBOARD-UX-OWNER-REVIEW-PENDING.md` et attendre la revue de David pour la
direction visuelle.

## 8. Rapport final

Rapporter par niveau les fixtures, objets R2 lus, octets, temps, cellules fermées,
gates, décision Council, commits et CI. Séparer les coûts observés des limites
inconnues du compte. Rapporter séparément couverture, propriétés, hypergraphe,
dashboard et sécurité. Ne jamais présenter un artefact GitHub comme source unique.
