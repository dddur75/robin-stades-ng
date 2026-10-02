# Reprise collecte — implementation plan

> **For Codex:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task by task.

**Goal:** Exécuter le mandat `ROBIN_REPRISE_COLLECTE_20261002` avec deux captures réelles The Odds API au maximum, les conserver de manière immuable dans R2, les rejouer hors ligne et livrer une vue privée consultable sans publier les cotes dans le dépôt public.

**Architecture:** Un runner Python dédié réutilise le transport HTTPS strict et le stockage R2 conditionnel existants. Il valide un manifeste V3.1 limité, réserve chaque tentative dans R2 avant l'appel, audite immédiatement la première réponse et n'autorise la seconde que si quota, données, persistance et replay sont prouvés. GitHub Actions ne fait qu'orchestrer ce runner sur `main`; il chiffre la restitution avant tout upload public.

**Tech Stack:** Python 3.12, pytest, boto3/R2 existant, transport TLS standard existant, GitHub Actions, OpenSSL CMS.

---

### Task 1: Autorité V3.1 et preuve d'activation

**Files:**
- Create: `configs/execution/reprise-collecte-20261002.json`
- Modify: `configs/agents/agent-report-schema-v3.json`
- Modify: `configs/agents/mission-activation-matrix-v3.json`
- Modify: `reports/council/decision-ledger.jsonl`
- Modify: `reports/evidence/evidence-graph.json`
- Test: `tests/council/test_reprise_collecte_governance_v1.py`
- Modify: `tests/council/test_robin_council_os_v3.py`

- [ ] Écrire les tests ciblés du manifeste exact à huit champs, des plafonds et de la nouvelle mission; constater leur échec.
- [ ] Ajouter le plus petit contrat d'autorité, puis un record `MISSION_AUTHORIZED` canonique chaîné au ledger et sa preuve.
- [ ] Exécuter uniquement les tests de gouvernance ciblés jusqu'au vert.

### Task 2: Runner borné, audit et restitution privée

**Files:**
- Create: `src/robin/capture/reprise_collecte.py`
- Create: `scripts/run_reprise_collecte.py`
- Test: `tests/capture/test_reprise_collecte.py`

- [ ] Écrire des tests comportementaux couvrant deux succès, absence de retry, arrêt après la première capture invalide, comptabilité des crédits, persistance avant/après appel, replay des octets et génération JSON/CSV/HTML; constater leur échec.
- [ ] Implémenter le runner minimal avec injections uniquement aux frontières réseau, horloge, sommeil et stockage.
- [ ] Exécuter les tests ciblés et les contrôles lint/type pertinents.

### Task 3: Orchestration manuelle et chiffrement avant upload

**Files:**
- Create: `.github/workflows/90-reprise-collecte-pilot.yml`
- Test: `tests/capture/test_reprise_collecte_workflow.py`

- [ ] Écrire un test qui charge réellement le YAML et vérifie le contrat observable: déclenchement manuel seul, un seul essai, secrets existants, plafonds, artefact chiffré seulement; constater son échec.
- [ ] Ajouter le workflow minimal sans planification ni exposition des données.
- [ ] Exécuter les tests du domaine capture et gouvernance.

### Task 4: Revue indépendante, intégration et collecte réelle

**Files:**
- Modify: `reports/council/decision-ledger.jsonl`
- Modify: `reports/evidence/evidence-graph.json`
- Create locally outside Git: encrypted/decrypted delivery artifacts

- [ ] Obtenir les revues indépendantes budget/temporal, stockage/sécurité et qualité du code; corriger au plus deux lots.
- [ ] Ajouter l'entrée pré-commit exigée au ledger, vérifier la chaîne, puis committer et pousser le writer unique.
- [ ] Exécuter l'unique suite complète avant fusion, ouvrir la PR, vérifier les contrôles et fusionner dans `main`.
- [ ] Générer localement la paire de déchiffrement, déclencher une seule exécution sur le SHA exact de `main`, puis attendre son résultat sans redéclenchement automatique.
- [ ] Télécharger, déchiffrer et vérifier la restitution; contrôler les hashes R2, les deux heures distinctes, les lignes 1/N/2 et la consommation totale.
- [ ] Ajouter uniquement les métriques non sensibles et leurs `claim_id` au graphe/ledger si nécessaire, sans publier équipes ni cotes.
- [ ] Ouvrir la vue HTML locale et livrer les chemins, SHA, run et consommation en distinguant exécuté/préparé.
