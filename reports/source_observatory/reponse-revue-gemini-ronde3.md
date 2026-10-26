# Réponse à Gemini — ronde 3, PR #128

Correctifs locaux des constats 1 à 7, sans commit ni collecte réelle. Pilote **PARTIAL** : aucune acceptation indépendante ni montée en charge. Preuve des chiffres : `ENG.SOURCE_OBSERVATORY.ROUND3.20261026`, dans `verification-ronde3.json` et le graphe de preuves.

| Constat | Réponse et preuve dans `test_round3_regressions.py` |
|---|---|
| 1 — BLOQUANT | Agent complet et jokers reconnus ; priorité spécifique et Allow/Disallow conservés. CGU interdites bloquantes avant toute requête, même YouTube ; négations strictement locales. |
| 2 — BLOQUANT | Article sans identité stable refusé, faux bookmarks compris. Versions seulement pour la même publication. Date de publication explicitement identifiée ; aucune modification en v1 ni cote observée avant la version utilisable. |
| 3 — BLOQUANT | Sélection déplacée rattachée à son ancien emplacement sémantique ; sélection omise conservée. Combiné : matchs distincts, version pré-match pour chaque jambe. |
| 4 — BLOQUANT | Cote de jambe jamais attribuée au combiné, même avec guillemets/parenthèses. Règlement par sélection résolue, période/règle explicites ; identité absente : attente ; résultat avant kickoff ou sans règle : refus. |
| 5 — BLOQUANT | Atom : description média et titre conservés ; RSS blanc ignoré. **Retrait des visites futures contesté** : couverture globale = réussies/toutes les planifiées (§19). Le test maintient 1/8 avec source manuelle et créneaux futurs. |
| 6 — MAJEUR | Lot décodé/validé avant écriture ; publications et reçu écrits ensemble. Erreur sur second payload : aucune publication inscrite. Fuseau non décodable : octets inchangés. Panne disque : fail-closed. **Fuseau contesté** : le plan gelé est UTC, origine conservée ; source Europe/Paris intacte et sept conversions indépendamment vérifiées, sans fuseau imputé. |
| 7 — MINEUR | Évaluation directe refusée si l'utilisabilité précède l'observation de contribution ; validateur de secours strict sur le type int des métadonnées. |

**Limite C1 maintenue.** Plafond initial : **14/39 sources = 35,9 %**, soit 294/819 visites. Après refus systématique des CGU restrictives, même YouTube : **10/39 = 25,6 %**, soit 210/819 maximum. Une mention API/flux ne prouve pas une exception à une interdiction. Ce sont des plafonds hors réseau, jamais des réussites réelles. Les critères ≥80 % et ≥25 sources restent impossibles. Aucun dénominateur limité aux sources collectables.

**Constat 8 — HORS_PILOTE, non corrigé.** Classement/cohortes exclus de la chaîne demandée ; défauts laissés ouverts. Seule `pre_match_contributions()` change dans `ranking.py`, pour le constat 3.

**Mesures : 42 échecs avant correctif ; 44 tests ronde 3 passent**, dont deux caractérisations déjà conformes. Reproductions initiales sur Python du worktree ; recette finale sur **runtime Robin 3.12.14**, `PYTHONPATH=src` : **611 passent, 2 échecs préexistants**, en 85.23s (0:01:25). Échecs : `test_successor_is_non_runtime_and_reuses_the_parent_cumulative_budget` et `test_sqlite_successor_is_test_only_and_does_not_extend_runtime_authority` (`test_reprise_collecte_governance_v1.py`, hashes inchangés). Ruff, mypy (10 modules), Bandit et chemins absolus passent ; avertissements Bandit sur commentaires nosec existants. Fichiers Codex en LF, sans assert source, chemin local absolu ni majuscules.

Fixtures anciennes remises en cohérence avec ces invariants temporels et les jambes distinctes. Plan, registre et horaires gelés inchangés. Changements parallèles `RUSH-STATUS.md` et `rush/` préservés ; leur couverture sur seules sources collectables ne valide pas C1.

Grok bloqué au démarrage par son verrou de politique : aucune acceptation indépendante ni verdict de David. Tentative locale tracée, coût inconnu ; journal d'équipe hors périmètre inscriptible, non modifié. Aucun push, fusion ou déploiement.
