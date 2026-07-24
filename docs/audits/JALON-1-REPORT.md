# Jalon 1 — Fondation data temporelle fiable

Date : 2026-07-24
Statut : `VERIFIED`
Statut produit : `PARTIAL`
Paris réels : `PRODUCTION_LOCKED`

## Conclusion

Le dépôt dispose maintenant d'une fondation testée empêchant les fuites
temporelles connues, les doubles comptages de marchés neutres, les mutations
silencieuses du brut, les rapprochements d'identité par nom seul et les règlements
multi-bookmaker ambigus. Le jalon ne prétend pas démontrer une rentabilité.

## Critères de sortie

| Critère | Statut | Preuve |
|---|---|---|
| Politique temporelle globale | `VERIFIED` | `docs/architecture/TEMPORAL-DATA-POLICY.md`, tests temporels |
| Fuite arbitre inter-ligues | `VERIFIED` | passe globale et atomes explicitement séparés |
| Double comptage Vague 2B | `VERIFIED` | `docs/audits/JALON-1-DEDUPLICATION.md` |
| Identifiants internes stables | `VERIFIED` | service d'identité UUID et mappings temporels |
| Stockage brut append-only | `VERIFIED` | hash de contenu, création exclusive et tests d'immutabilité |
| Zéros suspects isolés | `VERIFIED` | 24 segments, 7 936 valeurs, exclusion par défaut |
| Modèle multi-bookmaker | `VERIFIED` | modèle canonique et moteur de règlement versionné |
| Contrat de cotes prospectives | `VERIFIED` | interface fournisseur et mock sans secret |
| Pipelines idempotents | `VERIFIED` | clé d'idempotence unique et test de double exécution |
| Base et migrations | `VERIFIED` | Alembic, PostgreSQL CI et SQLite reproductible |
| Santé et observabilité | `VERIFIED` | 13 contrôles structurés et dashboard HTML |
| Documentation | `VERIFIED` | politiques, dictionnaire, runbook et registre actualisés |

## Résultats techniques

- tests unitaires, intégration, temporalité, identité, immutabilité, idempotence,
  déduplication, zéros suspects, règlement, migrations et dashboard ;
- `ruff`, `mypy --strict`, `bandit`, `compileall` et `pip check` intégrés ;
- migrations testées en montée et retour arrière ;
- notebook `notebooks/jalon1_data_quality.ipynb` exécuté avec sorties réelles ;
- dashboard `docs/data-quality/health.html` généré à partir du dataset audité.

## Qualité du dataset legacy

Le moteur produit 13 contrôles couvrant schéma, unicité technique et métier,
complétude, domaine des scores, futur, fraîcheur, zéros suspects, couverture des
identités, observabilité des conflits de source, références orphelines,
distribution et volume. Le run de référence ne comporte aucun échec critique.

Les alertes restantes sont intentionnelles :

- le dataset historique n'est pas encore relié aux UUID internes ;
- sa provenance brute n'est pas disponible ;
- des segments contiennent des zéros artificiels probables ;
- l'intégrité référentielle ne peut pas être prouvée sur ce dataset legacy sans
  migration vers les entités internes.

## Audit Vague 2B

La correction réduit les tests statistiques de 13 420 à 13 152 et les résultats
reportables de 525 à 374. Elle retire 1 210 362 évaluations métier dupliquées sur
les marchés neutres du run corrigé. Aucune ambiguïté de représentant canonique
n'est observée.

## Décision

Le Jalon 1 est `VERIFIED`. Le produit reste `PRODUCTION_LOCKED` jusqu'à la collecte
de cotes prospectives réelles, une phase shadow et une décision explicite séparée.
