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
