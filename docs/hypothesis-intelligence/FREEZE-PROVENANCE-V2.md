# Provenance corrective du freeze V2

Le freeze V1 reste immuable et conservé comme preuve historique. Sa révision
`0057e1c…` ne contenait pas encore la Factory V1; il n'est donc plus actif.

La correction suit deux commits :

1. le commit source contient la règle, le moteur, l'identité canonique des
   compétitions, les contrats de prix et l'éligibilité ;
2. un commit suivant gèle une nouvelle version `2.0.0`, liée par `supersedes`
   à `1.0.0`.

Chaque contrat V2 contient :

```text
source_code_revision
source_tree_hash
registry_hash
rule_hash
price_contract_hash
generator_hash
frozen_at
supersedes
```

`frozen_at` est l'instant réel de génération du second commit. Aucun commit
n'est antidaté et aucun contrat V1 n'est réécrit.

## Ancre corrective effective

- source Git : `550b492a078487ccde33479424a61617ac7742da`
- tree Git : `6272b76f7350fbf56f44916e2782018949675bce`
- génération UTC : `2026-07-29T17:00:38.032546+00:00`
- hash générateur : `fdf1813fa44aac4432c0acf43a7b5a5fec6aeee04f62c2b1d64cc20da1f9a6fd`

Le hash générateur est le SHA-256 du JSON canonique `{chemin: blob Git}` des
huit sources exécutables suivantes, toutes lues dans le commit source :

```text
scripts/build_universal_hypothesis_genome.py
src/robin/hypothesis_intelligence/competition_identity.py
src/robin/hypothesis_intelligence/contracts.py
src/robin/hypothesis_intelligence/freeze_v2.py
src/robin/hypothesis_intelligence/grammar.py
src/robin/hypothesis_intelligence/prospective.py
src/robin/hypothesis_intelligence/registry.py
src/robin/hypothesis_intelligence/universal_engines.py
```

Le test de provenance recalcule ce hash depuis Git, vérifie la tree, impose
`frozen_at > commit_at`, contrôle les trois `supersedes` et le verrou de
promotion. Le commit de gel ne modifie aucun de ces huit fichiers.
