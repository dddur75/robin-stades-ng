# Publication réconciliée — mission 036

Le workflow 71 existant reçoit l'entrée manuelle `publication_catchup=true`.
Ce mode saute le job `fixture-bundles` entier, même si d'autres entrées sont
présentes. Il utilise le groupe de concurrence `historical-deep-r2-state` et
ne reçoit que les accès GitHub/R2. Les collecteurs et leurs budgets ne changent pas.

Le publieur importe uniquement l'adaptateur de stockage, aucun collecteur. Son
adaptateur refuse les écritures R2 et limite les délais/reprises réseau. Les
seules opérations R2 sont LIST sur les répertoires de reçus publics 027/029 et
GET sur les reçus et projections normalisées exactement référencées.

## Preuves et reprise

Chaque référence contient un chemin Parquet, sa clé R2 de projection et un
SHA-256. Le chemin et la clé doivent désigner le même objet dans le même
périmètre ; traversal, autre préfixe ou hash invalide bloquent l'exécution.
Les chemins 2025 sont exclus depuis les métadonnées, avant toute lecture de
leur objet. Les doublons de contenu sont dédupliqués ; deux hashes différents
pour un même chemin ne sont jamais arbitrés silencieusement.

L'inventaire Git seul ne prouve pas la conformité. Le SHA-256 des bytes de
chaque blob déjà publié est comparé au reçu. Un mauvais contenu est signalé,
jamais remplacé. Le clone est partiel : les blobs permis sont récupérés par
SHA explicite, sans checkout général ni fetch paresseux. Les SHA sélectionnés
utilisent `--refetch --no-filter` pour que la négociation d'un clone partiel
ne les considère pas déjà disponibles au seul motif que leur commit l'est.

Les objets absents sont lus à huit lecteurs, vérifiés avant ajout, publiés par
lots de 1 000 puis poussés sans force. Les commits de historical-data sont les
checkpoints durables ; aucun curseur ne permet de sauter un objet ancien. Un
nouveau lancement repart de l'état distant et réconcilie toutes les références.
Une requête encore en attente ne démarre pas après le budget ; les requêtes en
cours gardent leurs limites réseau. L'inventaire Git/reçus et l'hydratation ont
la limite ultime du job, avec une marge de vingt minutes pour l'upload final.

Sans `--catchup`, le même publieur ne traite qu'un lot : l'exécution planifiée
continue à progresser. Avec `--catchup`, il enchaîne les lots jusqu'à égalité,
puis relit l'inventaire des reçus. De nouveaux reçus entraînent une nouvelle
réconciliation dans le budget restant. Un objet R2 absent, corrompu ou
illisible reste explicitement bloquant ; il n'entraîne aucun rappel fournisseur.
Une course Git rejette le push ; elle ne réécrit aucune donnée distante.

## Rapport

L'artefact `mission036-publication-<run>-<attempt>` contient le manifeste figé,
le journal des lots et `publication-report.json`. Le rapport final est aussi
ajouté dans `reports/evidence/mission029/publication/<run>-<attempt>/` sur
historical-data, avec révision du code et révision des données contrôlées.

Les colonnes `expected`, `published`, `missing`, `mismatched` forment une
partition disjointe des objets attendus. Elles sont données globalement et par
phase : B calendriers, B événements, C joueurs, compositions (027 et autres
reçus de lineups), autres phases attestées et reçus eux-mêmes. Une partition
Parquet vide mais conforme à son hash est un objet publié ; elle ne prouve pas
la couverture d'un match ou d'un critère.

`COMPLETE` exige zéro manque, zéro incohérence et un inventaire de reçus stable.
`PARTIAL` conserve les objets qui n'ont pas été traités dans le budget ;
`BLOCKED` expose les preuves contradictoires ou objets indisponibles. Les
statistiques avant/après du stockage ne sont pas un taux de rattachement.
Celui-ci est recalculé séparément par `scripts/build_prematch_criteria.py`, sur
la même population figée de 70 084 matchs et avec l'audit temporel existant.
Le job manuel lance ce script après COMPLETE, en réutilisant les objets Git
déjà présents et en hydratant uniquement les anciennes familles permises qui
manquent au clone. Le calcul lui-même reste sans récupération réseau. Les
sept Parquet, l'inventaire source et les rapports de couverture sont inclus
dans le même artefact ; le dépôt de code est mis à jour après leur vérification.

Les détails Ligue 1 anciens sans fixture_id ne sont pas réinventés : un
rattrapage de publication ne reconstruit pas l'index de leurs observations.
Les critères inconnus restent nuls avec leur motif. Aucun calendrier toutes
compétitions, seuil de jaunes ou tirs horodatés n'est déduit de la publication.

### Compatibilité des reçus 027 historiques

Le premier dispatch `39395579612` a refusé une référence (`REFERENCE_SCOPE`),
avant toute projection publiée. Le producteur antérieur à `48a93765` conservait
le chemin absolu du runner dans `partitions[].path` :
`/home/runner/work/robin-stades-ng/robin-stades-ng/artifacts/historical-deep/mission027/`.
Cette seule racine connue est retirée pour la mission 027 ; le chemin obtenu
reste soumis au contrat canonique et doit correspondre exactement à la clé R2
attestée. Aucune lecture du chemin local du reçu, aucun alias libre, aucun
assouplissement du hash ou du holdout. Le test couvre aussi les racines étrangères
et la traversée de répertoires.
