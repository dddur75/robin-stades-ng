# Validation de livraison — mission 036 avant-match

**577 tests ciblés passent**, dont 28 tests avant-match. Le recalcul décalé
compare 172 lignes équipe-match après retrait des données post-match de la
cible et du futur. Un test supplémentaire lie les exports à l'empreinte exacte
du calculateur livré. Clés, hashes, bornes et couverture sont réconciliés.

La suite du dépôt entier a terminé : **4 066 réussites, 50 tests ignorés,
36 échecs** (1 052,22 s). Elle a démarré avant les derniers correctifs ciblés.
Un échec introduit de provenance a été corrigé : rôle C0 enregistré, hash de
l'artefact réellement référencé, nœuds de décisions complets, chemins de fichiers
concrets dans le contexte de commit. Les anciens records du journal sont
préservés ; l'historique de l'échec et de sa correction est explicite.
Les 142 tests de gouvernance/portabilité passent dans les 577 tests finaux.

Les 35 autres échecs concernent les modules de capture existants, inchangés :
la configuration de confiance TLS de ce cloud est refusée par leur transport
strict, et deux tests de descendants de processus obtiennent
`WORKSPACE_COMMAND_TERMINATION_UNCONFIRMED`. Un cas TLS et les deux cas de
processus ont été reproduits sur une archive de main. Aucun appel réseau non
autorisé n'est signalé par la garde de capture. Les noms de chaque test en
échec et le nombre de cas paramétrés figurent dans `VALIDATION.json`.

Les temporaires utilisent un stockage local autorisé (le tmpfs par défaut
n'est pas accepté par CaptureStore). La configuration TLS/proxy héritée est
préservée. Aucun assouplissement des contrôles de capture n'a été effectué.

Après normalisation LF des CSV, les 28 tests avant-match et le contrôle de
provenance sont relancés : **29 réussites**. Les valeurs des critères et les
taux de couverture sont inchangés.

Ruff, mypy strict, Bandit au seuil moyen/haut, recherche de secrets et
`git diff --check` passent. Le journal reste append-only, toutes les preuves
antérieures sont conservées. Seuls deux fichiers préexistants changent : le
journal et le graphe de preuves. Workflows, collecteurs, configurations figées,
robin-core et données source restent inchangés. Aucun appel fournisseur, accès
R2, écriture Neon ou pari. Revue indépendante en attente ; aucune fusion.

## Correction de la CI demandée dans la relecture de PR #121

Sur `bfa4f61`, le job `Quality and domain tests` (run `39343979390`, job
`118374496070`) passe le lint et le typage puis échoue à **Securite basique** ;
les tests sont ignorés après cet échec. La reproduction donne exactement
**quatre alertes Bandit Low/High-confidence** dans `sources.py` : B404 à l'import
de `subprocess`, B603 sur deux `check_output` et un `Popen`. La vérification
locale précédente avec `-ll` ne contrôlait que les sévérités moyenne/haute,
alors que la CI n'a pas ce filtre : c'était une lacune de validation.

Les quatre exceptions sont limitées aux IDs et lignes concernés, avec motif :
Git local en argv, sous-commandes fixes, aucun shell, protocoles refusés et
lazy fetch désactivé. Le comportement du programme est inchangé, vérifié par
comparaison AST hors docstring. Le workflow et le seuil Bandit restent intacts.
La commande Bandit complète de CI passe désormais, ainsi que Ruff, mypy strict
et les **28 tests avant-match**. Les sorties sont régénérées avec l'empreinte
du calculateur actualisée ; valeurs, couverture et audit décalé inchangés.
Le statut distant final du job est publié dans la description de PR après push.
