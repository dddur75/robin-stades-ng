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
