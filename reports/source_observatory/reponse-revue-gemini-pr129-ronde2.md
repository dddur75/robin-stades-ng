# Réponse à Gemini — PR #129, ronde 2

Constats **1, 2, 3 et 5 corrigés localement**, sans pull ni commit, sur
`codex/observatoire-sources-v3`, HEAD `1c4260ff`. Aucun scénario de ces constats
n'est contesté. Les constats 4 et 6 restent hors de cette intervention.

| Constat | Échecs observés avant son correctif | Correctif ciblé |
|---|---:|---|
| 1 | 28 | Bornes de mots/décimales ; cote complète requise dans l'extrait et validée sur la clause entière, sans fenêtre de préfixe limitée ; contexte conservé dans la preuve ; contexte incertain dépassant 500 caractères refusé. |
| 2 | 10 | Doublons rejetés avant création des brouillons, lignes décimales équivalentes comprises ; adjectif « nul » distinct du pari nul ; total d'équipe et disjonction sans cote ; combiné explicite et cote totale/globale pris en charge. |
| 3 | 23 | Négations, questions, conditions et instructions injectées contrôlées sur la clause source ; préfixe « Sans jouer, » compris. |
| 5 | 11 | Choix d'équipe lié littéralement à une intention ou à « vainqueur », même sans résultat de `_picks` ; clauses découpées une fois et réutilisées ; « pas » et « si » étrangers à la sélection n'annulent pas le choix. |

Les tests ont été écrits puis exécutés en échec avant chaque correctif :
**72 échecs observés**, plus **7 contrôles déjà passants**, soit **79 nouveaux
scénarios désormais passants**. Les tests de route retournent effectivement le
pronostic ; les assertions portent aussi sur les brouillons journalisés.
Les preuves restent des sous-chaînes contiguës bornées, avec texte conservé
uniquement si permis. Aucun brouillon n'est promu en contribution acceptée.

Recette sur **Robin Python 3.12.14** :
`PYTHONPATH=src pytest tests/source_observatory tests/council tests/hypothesis_intelligence`
(avec affichage court et cache pytest désactivé) : **867 réussis, 2 échecs en
92,14 s**. Référence avant correctif : **788 réussis, les mêmes 2 échecs**.
Ils restent dans `tests/council/test_reprise_collecte_governance_v1.py` :
`test_successor_is_non_runtime_and_reuses_the_parent_cumulative_budget` et
`test_sqlite_successor_is_test_only_and_does_not_extend_runtime_authority`
(divergence préexistante du hash du manifeste parent).

Ruff, mypy, Bandit, chemins, LF, absence d'assertions dans le code source et
noms de chemins en minuscules sous `src/robin` : contrôlés. Le premier lancement
via l'alias Python était inaccessible ; le venv local manquait de dépendances ;
la recette finale utilise bien le runtime Robin existant, sans installation.

**PARTIAL pour l'acceptation indépendante** : Grok refuse son verrou de politique ;
Gemini attend une authentification. Aucun verdict de relecteur ni de David reçu.
Coûts inconnus ; journal du banc hors périmètre inscriptible, reçus locaux conservés.
Aucune montée en charge, fusion, publication ni action de production.

Preuve : `ENG.SOURCE_OBSERVATORY.PR129.ROUND2.20261026` dans le graphe de preuves ;
[recette et cycles rouge/vert](verification-pr129-ronde2.json),
[Grok](relecture-grok-pr129-ronde2.json),
[Gemini](relecture-gemini-pr129-ronde2-correctif-final.json).
