# Conformité au dossier décisif — 26/10/2026

Spécification : REGLES-DOSSIER-CONCEPTION.md, §04/05/17/19.
Rédacteur unique : Codex, worktree observatoire, aucun commit ni effet externe.

Approche : conserver les objets immuables et le journal append-only. Ajouter
les métadonnées manquantes et les événements de correction ; reconstruire les
bilans depuis les preuves, sans supprimer les pertes ou les identités d'origine.

- [x] Tester puis compléter les contributions, preuves permises et horodatages
  UTC avec fuseaux d'origine ; chaîner les versions et figer la version pré-match.
- [x] Tester puis ajouter les règles documentées/versionnées : 1N2 réglementaire,
  qualification, totaux, handicaps à quarts de ligne et combinés ; toute règle
  absente ou non prise en charge laisse le résultat en_attente.
- [x] Tester puis calculer groupes de reprises attestées, révisions d'identité,
  séparation/recalcul, retraits et couverture de visites. Les similarités seules
  ne fusionnent rien ; un retrait suspend Comparable et conserve le bilan.
- [x] Séparer les quatre catégories du §05 et leurs métriques ; synchroniser
  le schéma fermé, vérifier tests du domaine, lint et typage du module.

Vigilance : découverte tardive, correction après match, plusieurs sélections
d'une publication, fuseau DST, reprise cyclique, règle de report inconnue,
combinaison de demi-règlements, retrait d'une perte et séparation après reprise.

État initial Git conservé dans la sortie de session : branche
codex/observatoire-sources-v1, HEAD 227b5ae1f188a58b80c6d645faf64ff7f1c9507a,
origin https://github.com/dddur75/robin-stades-ng.git ; main dans un autre
worktree. Modifications déjà présentes : ledger, data/source_observatory,
reports/source_observatory, src/robin/source_observatory, tests/source_observatory.

Relecture ind?pendante : deux tentatives Grok 4.7 high ont ?chou? avant
r?ponse, verrou de politique Grok inaccessible dans le sandbox. Aucun avis
re?u, aucune validation ind?pendante ni mont?e en charge. Le journal global
du banc est hors racine inscriptible ; re?us locaux conserv?s, sans y ?crire.
