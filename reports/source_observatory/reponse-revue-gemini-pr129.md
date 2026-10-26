# Réponse à Gemini — PR #129, tâche B

Correctifs 1–5, 7–8 et 10 vérifiés ; constat 9 documenté sans affaiblir
`_endpoint`. Tâche A conservée ; constat 6 hors périmètre. Aucun commit ni pull.

| Constat | Réponse et preuve ciblée |
|---|---|
| 1 | Décimale avec séparateur obligatoire, valeur ≥ 1, contexte cote/@/prix dans l'extrait. Entiers, ligne, xG, mise, pourcentage et ancienne cote écartés. |
| 2 | Marché, sélection et ligne confrontés à l'extrait ; buts et handicap signé contrôlés. Prose, Markdown et plusieurs enveloppes rejettent toute la réponse. |
| 3 | Le texte reste une donnée JSON. Aucun mot magique ne configure les contrôles. Négation, hypothèse et historique contrôlés dans la clause contenant l'extrait, même si celui-ci masque la négation. |
| 4 | Plus de 500 caractères : rejet, sans troncature. Les offsets sont contrôlés même avec `text=None`. Un extrait littéral court nécessite toujours `preuve_permise` pour être conservé en clair. |
| 5 | Hash LF ancré dans le code et le schéma, vérifié dans `ExtractionRecord` et le fichier freeze ; présent dans chaque retour et enregistrement d'extraction journalisé. Normalisation CRLF→LF, historique du gel conservé, attribut Git LF ajouté. |
| 7 | Préfiltre supprimé : la route est appelée même sur texte vide ou sans pari. La validation reste en aval. |
| 8 | Unicité des brouillons dans leur extraction ; lignage Publication/Version conservé. Une Contribution déjà acceptée ne concurrence plus leur emplacement. |
| 9 | `a_construire` décrit le travail de connecteur, pas une autorisation de collecte. État actuel : 59 sources, 45 `a_construire`, 23 endpoints retenus et 22 refusés : 4 CGU inconnues, 18 refus contractuels. Les chiffres 36/17 de la revue ne décrivent plus ce registre. Les sources YouTube citées rencontrent actuellement le refus contractuel avant le contrôle de flux. Aucune autorisation ni URL de flux inventée ; `_endpoint` inchangé. |
| 10 | Instruction inaccessible après `continue` supprimée ; contrôle AST. |

Reproduction isolée sur les quatre modules de HEAD : **56 échecs, 17 réussites**
sur les 73 cas alors présents, avant application des correctifs dans cette copie.
Les deux cas LF/CRLF ont aussi échoué sur le code local avant normalisation.
Les trois tests du constat 9 caractérisent un verrou déjà correct ; aucun
correctif d'autorisation n'est justifié.

Recette **Robin Python 3.12.14**, `PYTHONPATH=src` : **533 tests passent en 4,47 s**,
dont 92 cas PR #129. Avec sources copiées et prompts LF hors dépôt : **533 passent
en 4,81 s**. Contenu du prompt vérifié : hash LF
`69dafca29b2de56467427b0ff475bbcfaef27491d52a4c685304b2a8f567fe70` ; sa copie CRLF
correspond au hash historique `2c2ba78b…`.

Council/Hypothesis : **255 passent, 2 échecs préexistants en 101,04 s** :
`test_successor_is_non_runtime_and_reuses_the_parent_cumulative_budget` et
`test_sqlite_successor_is_test_only_and_does_not_extend_runtime_authority`
dans `test_reprise_collecte_governance_v1.py` ; même divergence de hash du manifeste
parent que dans la preuve T4e. Ruff, mypy (12 modules), Bandit et contrôles de
chemins/LF/assert passent ; avertissements Bandit sur commentaires existants.

**PARTIAL pour l'acceptation indépendante** : Grok refuse l'accès au verrou de
politique ; Antigravity n'est pas authentifié. Aucun verdict de relecteur ni de
David reçu. Aucune montée en charge ni action externe.

Preuve : `ENG.SOURCE_OBSERVATORY.PR129.B.20261026`,
[recette](verification-pr129.json), [recette LF](verification-pr129-lf.json).
Les erreurs de montage du premier essai temporaire sont conservées dans ce reçu.
