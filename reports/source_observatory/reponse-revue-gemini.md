# Réponse à la revue Gemini — PR 127

Codex, rédacteur unique, 26/10/2026. Aucun commit, push ou effet en production.
Base locale : `5c087f5a1b7a7720642171ebb5faf5a168a55a5b`.
Le `git pull --ff-only origin codex/observatoire-sources-v1` demandé a échoué :
le sandbox refuse l'écriture de `FETCH_HEAD` dans les métadonnées du worktree.
La synchronisation distante n'est donc pas attestée.

| Constat | Réponse et correction |
| --- | --- |
| 1 — Retrait/omission | Confirmé. Dernière contribution par emplacement ; omission et retrait conservent la perte et suspendent Comparable. Auteur retiré toujours visible ; dernier résultat sans évaluation : rapport refusé. |
| 2 — Identités | Confirmé. Affectations appliquées uniquement avec `certainty='attestee'`. Fusion sur similarité refusée, alias similaire ignoré. |
| 3 — Injection tardive | Confirmé. `Contribution.observed_at` obligatoire, conservé au stockage ; disponibilité tenant compte de cette observation. Antidatage refusé ; ajout au/après coup d'envoi rétrospectif. Correction observée et strictement croissante obligatoire. |
| 4 — Second rapprochement/cohorte tardive | Confirmé. Second MatchMarket de la même contribution interdit ; aucun nouvel identifiant ne contourne l'audit. Cohorte antidatée derrière les observations/résultats refusée. |
| 5 — Reprises/ROI | Confirmé. Graphe global, y compris intermédiaires non évalués d'autres auteurs ; déduplication par origine, match, marché, sélection et catégorie avant sommes/moyennes. Cycle avec racine externe non résolu. |
| 6 — Règlement | Confirmé. Ligne ignorée, total négatif, combiné à une jambe : en attente. Jambes prouvées, pré-match, cotes/règles/résultats cohérents obligatoires ; sans preuves, aucune évaluation rentable. |
| 7 — États/couverture | Confirmé. `rankings(..., at=...)` dérive les états des entités du journal : fenêtres, sources, visites, résultats et base de cote choisie. Test après réouverture du JSONL, découverte sans résultat et réserve prospective. |
| 8 — Extraits | Confirmé. Cinq emplacements maximum, dont un seul textuel, total de 500 caractères et aucun chevauchement ; schéma synchronisé, texte blanc refusé. |
| 9 — Identité match/catégories sans cote | Confirmé. Rapprochement résolu incohérent refusé ; Brier et exactitude indépendants du choix déclaré/observé. |
| 10 — Tests | Assertion de provenance remplacée par une persistance entre sources distinctes. Intégration cohorte/journal ajoutée ; tests unitaires de transitions conservés. Encodage des documents corrigé. |

Nuances contestées : l'absence de lien de reprise ne prouve pas qu'une publication
est originale ; elle reste inconnue (test des origines inconnues conservé).
Une cote **déclarée par l'auteur** peut précéder sa découverte par Robin : elle
n'antidate ni la version ni la contribution. La fixture rétrospective conserve
cette distinction, avec une observation de contribution désormais explicite.
Les constantes dans un test unitaire de transitions ne sont pas une tautologie ;
elles ne suffisaient cependant pas à vérifier l'intégration au journal.

Tests synthétiques : 11 échecs initiaux sur les blocages, puis reproduction des
majeurs avant correction ; régressions dans `tests/source_observatory/test_review_regressions.py`.
Commande finale : `PYTHONPATH=src pytest tests/source_observatory -p no:cacheprovider --basetemp=<dossier temporaire hors dépôt>`.
Résultat : **126 tests réussis**. Ruff et mypy ciblés réussis ; `git diff --check` réussi.
Bandit n'est pas installé ; aucune nouvelle relecture indépendante des corrections.

Contraintes : aucun `assert` dans `src/`, aucun nom de fichier avec majuscule
sous `src/robin`, aucun chemin local absolu dans les fichiers livrés ici.
Les chemins de la revue et de l'ancien diagnostic Grok ont été masqués sans
changer leurs verdicts. Dette préexistante hors lot : le ledger append-only
du Council et l'ancien reçu `verification-conformite.json` contiennent encore
des chemins locaux. Ils sont conservés : réécrire le reçu invaliderait son hash
dans le graphe de preuves. La contrainte globale sur tout le dépôt reste donc
**PARTIAL**, comme la synchronisation distante.
Les anciens journaux sans observation de contribution/certitude d'identité sont
refusés, sans migration silencieuse ni horodatage inventé.
