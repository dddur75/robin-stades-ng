# Mission compilée — P0 E1 Real Fixture Proof V1

Tu es Codex dans Robin des Stades. Exécute uniquement la mission E1 décrite ci-dessous. Ne lance pas E2 et ne déploie rien.

## 1. Préconditions

1. Vérifie que la PR `Historical Coverage Denominator Closure V1 — grains, preuves et readiness P0` a été revue puis fusionnée explicitement.
2. Vérifie que `main` contient son commit de fusion et que la CI distante correspondante est verte.
3. Ne modifie jamais le checkout d’accueil protégé. Crée un worktree distinct depuis ce `main` et la branche `codex/p0-e1-real-fixture-proof-v1`.
4. Lis `AGENTS.md`, le ledger Council, le graphe de preuves, le contrat de dénominateurs P0, le catalogue des grains et les packs E0–E4 avant toute écriture.
5. Maintiens `STORAGE_PAUSED=true`, `P3_P4_PAUSED=true`, `PRODUCTION_LOCKED=true`, `REAL_BETS=false`, `NO_BET_DEFAULT=true`, `PROMOTION_LOCKED=true`, `SOCIAL_PUBLISHING_ENABLED=false` et `DEMO_MODE_ENABLED=false`.

Si une précondition manque, arrête avec `P0_E1_REAL_FIXTURE_PROOF_PARTIAL`.

## 2. Autorisation bornée

Réutilisation en lecture seule des payloads et reçus déjà prouvés par PR #26 : autorisée.

Tout le reste est interdit par défaut :

- appels fournisseur : 0 ;
- achats et crédits cotes : 0 ;
- nouveaux replays : 0 ;
- écritures/suppressions R2 : 0 ;
- requêtes SQL distantes : 0 ;
- déploiements Sites/Pages : 0 ;
- paris, promotions et publications : 0.

## 3. Boucle E1

### E1.0 — inventaire de preuve

- Réconcilie les manifests, hashes, reçus et identités déjà disponibles.
- Ne copie aucun payload brut dans Git.
- Produis un inventaire borné des candidats P0 admissibles.

### E1.1 — manifeste avant calcul

Choisis exactement 10 fixtures réelles dans un même couple compétition-saison :

- fixture complète et P0 ;
- compétition, saison, kickoff et deux équipes canoniques ;
- provenance d’identité vérifiable jusqu’au reçu ;
- tri par `kickoff_utc`, puis `fixture_id`.

Écris et valide le manifeste de sélection avant de calculer les familles. Moins ou plus de 10 fixtures est un échec fermé.

### E1.2 — redesign de provenance

Ne relance pas le workflow Deep Data Cockpit inchangé. Remplace son hypothèse implicite d’identité par un registre explicite : identité canonique, source, reçu, hash, décision de rapprochement et objection éventuelle.

Une identité ambiguë ou non vérifiée reste `OPEN_IDENTITY_PROVENANCE` et exclut la fixture ; elle n’est jamais devinée à partir d’un nom.

### E1.3 — census borné

Pour chaque fixture et chaque famille applicable :

- applique le grain autoritatif ;
- calcule attendu, reçu, vide valide et invalide ;
- conserve les doublons exacts comme une seule preuve ;
- bloque les doublons contradictoires ;
- classe les absences ambiguës `UNCLASSIFIABLE` ;
- calcule séparément `scope_completion`, `normalization_integrity` et `content_presence` avec numérateur et dénominateur ;
- n’emploie jamais `coverage_rate` ou `overall_rate`.

### E1.4 — conclusion

E1 réussi signifie seulement que la chaîne fonctionne sur 10 fixtures réelles. Maintiens `can_close_real_cell=false`, `0/480` cellule fermée et tous les gates P0 bloqués.

N’ouvre pas E2, E3, E4, l’hypergraphe, les backtests ou les écrans de performance.

## 4. Validation

Exige au minimum :

- tests du manifeste exact 10 fixtures ;
- Golden Pack E1 et mutations d’identité, doublons, absence, vide valide et taux ;
- reproduction déterministe des artefacts et hashes ;
- Ruff, schémas JSON, secret scan et diff check ;
- tests de confidentialité et de frontière serveur des sources compactes ;
- tests Cockpit ciblés si le Desk est mis à jour ;
- revue indépendante red-team ;
- CI distante sur le head exact de la PR.

Deux échecs identiques d’une architecture imposent `REDESIGN_REQUIRED`; ne lance pas une troisième tentative inchangée.

## 5. Gouvernance et GitHub

- Un seul writer par worktree.
- Ledger append-only et graphe de preuves mis à jour avant chaque commit.
- Crée une PR brouillon, ne la fusionne pas.
- Titre recommandé : `P0 E1 Real Fixture Proof V1 — 10 fixtures, identités et census`.
- Aucune montée en charge sans nouvelle décision Council explicite.

## 6. Rapport final

Rapporte : environnement, sélection des 10 fixtures, provenance, grains, census, trois taux, erreurs, tests, objections, coûts et effets externes.

Termine par un seul verdict :

```text
P0_E1_REAL_FIXTURE_PROOF_READY_SAMPLE_ONLY
```

ou :

```text
P0_E1_REAL_FIXTURE_PROOF_PARTIAL
```

Ne présente jamais E1 comme une fermeture P0 complète.
