# Validation actuelle — rattrapage de publication du 20 octobre 2026

Publication **COMPLETE** : **144 071 / 144 071** références attestées, aucun
manque ni SHA-256 discordant, inventaire de reçus stable. Exécution
`39438595883`, code `64b8b3668b6073d6e4605a9e1e601c2c6207a529` ; source analytique
immuable `8558719f1e91dc2e81e3a285848ec145a77f3f54`. Le rapport final original
est conservé sur historical-data et dans l'artefact12274480581 ;
`AFTER-PUBLICATION.json` ajoute seulement la provenance et les passages antérieurs.

Rattachement : **17 433 / 70 084 (24,87 %) → 70 084 / 70 084 (100 %)**, sans
changer les IDs cibles. ForceXI : **9 580** équipe-matchs calculables ; état
score/buts : **118 024** ; points tardifs : **128 340**. Les 225 cellules
ligue-saison et 2 250 lignes de couverture sont réconciliées avec les Parquet.

La livraison analytique reste **PARTIAL** : **l'objectif Abs non nul n'est pas
atteint**. Sur les 14 452 XI officiels, 11 798 lignes manquent de minutes
historiques complètes et 2 654 de statistiques de saison complètes ; les
125 716 autres lignes n'ont pas de XI valide. Le recoupement de 14 022 XI/blocs
joueurs n'établit pas les minutes requises. Aucune valeur inconnue, notamment
au banc, n'est convertie en zéro. Voir `ABSENCE-SOURCE-GAP.json` et les motifs
par ligue/saison dans `coverage.csv`. Les tirs horodatés, calendriers toutes
compétitions et règles de cumul restent également non prouvés.

Validation ciblée finale : **102 réussites, 1 XFAIL strict, 7,93 s**. L'essai
initial de réception des nouveaux exports donne **29 réussites et 1 échec en
5,51 s**, exactement sur l'objectif Abs>0. Cet objectif et son audit sur une valeur réellement
calculable restent dans un test séparé en échec attendu strict, limité à
`AssertionError` ; un futur XPASS fera échouer la suite jusqu'à levée explicite
de cette limite. Les tests ordinaires contrôlent le statut PARTIAL et les
raisons exactes de la lacune, le rattachement et ForceXI réellement calculable.
Les tests synthétiques positifs d'Abs et les formules sont inchangés.

L'audit décalé vérifie **1 026** lignes équipe-match après suppression des
données post-match de la cible et du futur. **37** lignes auditées contiennent
ForceXI non nul. Les hashes des résultats et leurs listes non_null sont liés
aux valeurs effectivement livrées ; aucun audit Abs réel non nul n'est affirmé.
Les 136 866 entrées d'inventaire sont hachées ; les 136 810 entrées communes au
manifest des reçus ont exactement son SHA-256. Les 56 entrées héritées gardent
leur provenance antérieure. Saison2025 exclue avant lecture.

Revue C4 indépendante : `reports/council/mission036-publication/C4-data-review.json`.
Les contrôles de données sont effectués hors réseau ; aucun nouvel appel
fournisseur, écriture Neon/R2, pari ou fusion. Le rattrapage réutilise seulement
les archives déjà collectées ; les jobs indépendants préexistants de main ne
sont pas déclenchés par cette PR. Le correctif de reprise ne permet qu'une
ronde de lecture supplémentaire, dans le même plafond global, jamais sur
absence, hash contradictoire ou push. Son usage effectif est zéro dans le run
final, le premier GET du passage final ayant rendu l'objet restant (SDK borné).

Ruff, mypy strict et Bandit toutes sévérités passent. La CI complète du code
initial141 (run39397203825) est une preuve historique distincte : 4 129 tests
réussis, 41 ignorés. La CI du commit final de données est vérifiée après push
et liée dans la PR ; aucun résultat futur n'est présenté ici comme acquis.
Les claims `DATA.MISSION036.PUBLICATION.V1` (publication vérifiée) et
`DATA.MISSION036.PREMATCH.V1` (critères PARTIAL) gardent cette distinction.

Les fichiers `ATTACHMENT.md`, `ATTACHMENT-AUDIT.json` et
`attachment-coverage.csv` décrivent **le diagnostic historique avant rattrapage
sur fac718f3**. Ils ne sont pas une validation des nouveaux exports. L'ancienne
validation ci-dessous et les champs historiques de `VALIDATION.json` sont
conservés pour tracer les échecs et leurs corrections.

## Historique PR #121 — source fac718f3, avant le présent rattrapage


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
