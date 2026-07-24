# Robin des Stades — État du projet

Dernière mise à jour : 2026-07-24
Dépôt : `dddur75/robin-stades-ng`
Branche : `codex/foundation-v1`
Mode : `SIMULATION`
Paris réels : `PRODUCTION_LOCKED`

## État global

`PARTIAL` — la fondation data du Jalon 1 est vérifiée, mais le produit n'a encore
ni archive prospective réelle de cotes, ni validation shadow, ni autorisation
d'exécution de paris.

## Jalons

| Jalon | Statut | Preuve principale |
|---|---|---|
| 0 — audit initial | `VERIFIED` | `docs/audits/JALON-0-AUDIT.md` |
| 1 — fondation data temporelle | `VERIFIED` | `docs/audits/JALON-1-REPORT.md` |
| 2 — collecte versionnée | `PARTIAL` | contrats prêts, archive réelle absente |
| 3 — expérience produit | `PARTIAL` | rapport santé statique opérationnel |
| 4 à 9 | `NOT_STARTED` | hors périmètre du cycle |

## Fondation opérationnelle

- politique point-in-time avec instants UTC et features immuables versionnées ;
- statistiques arbitre séparées en global, compétition et saison, calculées dans
  une passe chronologique globale et par lots de matchs simultanés ;
- marchés neutres Vague 2B ramenés à un représentant fixture canonique ;
- identités internes UUID et correspondances fournisseur à validité temporelle ;
- stockage brut append-only, adressé par hash, rejouable et sans secrets ;
- statut `SUSPECT_ZERO` conservé pour audit et exclu des modèles par défaut ;
- modèle canonique `market_opportunity` → `bookmaker_quote` → `selected_bet`
  → `settled_bet` ;
- contrat de snapshots de cotes et fournisseur mock sans clé API ;
- schéma SQLAlchemy, migrations Alembic, transactions et idempotence des runs ;
- 13 contrôles qualité structurés et dashboard de santé généré ;
- CI : lint, typage strict, sécurité, migrations PostgreSQL, tests et smoke test.

## Données auditées

- 36 423 matchs, 9 ligues, 11 saisons ;
- 0 doublon de `match_id`, 0 doublon de fixture métier, 0 score final manquant ;
- 792 segments colonne–compétition–saison audités ;
- 24 segments `SUSPECT_ZERO`, soit 7 936 valeurs conservées mais isolées ;
- dataset legacy non encore migré vers les UUID et la provenance brute : alertes
  visibles, non masquées.

## Verrous maintenus

- aucune cote prospective réelle archivée ;
- aucune validation shadow hors échantillon ;
- historique legacy à recollecter depuis des réponses brutes versionnées pour
  résoudre les zéros suspects ;
- résultats exploratoires Vague 2B et ROI toujours `UNVERIFIED` comme preuve de
  rentabilité ;
- aucune exécution de pari réel.

## Action utilisateur

Aucune. Voir `USER-ACTION.md`.
