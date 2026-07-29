# Hypothesis Intelligence Factory V1

## Objet

La factory transforme des résultats de recherche historiques en objets
auditables sans les présenter comme des preuves de robustesse. Elle conserve
séparément la découverte, la validation, l'observation prospective et la
décision humaine.

## Architecture

- `DiscoveryEngine` importe et normalise les découvertes.
- `ValidationEngine` applique les contrôles et les transitions autorisées.
- `ProspectiveObservationEngine` évalue l'éligibilité d'un fixture selon un
  contrat préenregistré.
- `HypothesisLedger` enchaîne les événements par hash dans un journal
  append-only.
- Le registre canonique relie versions, métriques, contrats, observations,
  règlements et historique des statuts.

Les origines obligatoires sont :

- `MACHINE_DISCOVERED` ;
- `OWNER_PROPOSED` ;
- `MODEL_DISCOVERED` ;
- `LITERATURE_PROPOSED`.

Une hypothèse ne change jamais d'origine au cours de son cycle de vie.

## Identité, variantes et classement

Le fingerprint canonique couvre le marché, la sélection, la compétition, les
bornes de cote, la marge, les conditions et le cutoff temporel. Les règles
exactement identiques sont regroupées ; les variantes gardent leur parent et
leur famille.

Le classement expose séparément support, rendement, walk-forward, stabilité,
risque de fuite, tests multiples et contrôles négatifs. Le score composite est
une aide au tri transparente, pas une preuve statistique ni un statut.

Les métadonnées d'explication peuvent résumer une règle, ses facteurs et ses
limites. Elles ne peuvent ni modifier les métriques, ni promouvoir un statut,
ni fabriquer une confiance, ni remplacer le protocole préenregistré.

## Persistance

La migration `0011_hypothesis_intelligence_v1` ajoute sept tables :

1. `hypothesis_registry` ;
2. `hypothesis_versions` ;
3. `hypothesis_discovery_metrics` ;
4. `hypothesis_prospective_contracts` ;
5. `hypothesis_observations` ;
6. `hypothesis_settlements` ;
7. `hypothesis_status_events`.

Les tables d'événements prospectifs sont protégées contre les mises à jour et
les suppressions. Les payloads bruts fournisseur n'y sont jamais stockés.

## État réel au gel V1

- 116 fixtures réels déjà collectés ;
- 0 prédiction réelle ;
- 0 règlement réel ;
- 0 entraînement réel ;
- production, pari réel, publication sociale et appels fournisseurs verrouillés.

## Exploitation future

La cadence future peut reconstruire les pages du registre, ouvrir des
observations uniquement lorsque les prix admissibles existent, régler les
observations après résultat définitif, puis produire les checkpoints 30, 80 et
fin de saison. Une décision humaine reste obligatoire avant tout changement de
statut vers `VALIDATED`.
