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
dispose de 300 s de transfert après préparation et vérification de l'inventaire.
La préparation ne consomme donc pas à elle seule le budget du lot ordinaire ;
la durée totale reste bornée par le timeout du job existant, non augmenté.
Avec `--catchup`, la préparation reste incluse dans le budget global de 9 600 s ;
il enchaîne les lots jusqu'à égalité,
puis relit l'inventaire des reçus. De nouveaux reçus entraînent une nouvelle
réconciliation dans le budget restant. Un objet R2 absent, corrompu ou
illisible reste explicitement bloquant ; il n'entraîne aucun rappel fournisseur.
Une course Git rejette le push ; elle ne réécrit aucune donnée distante.

## Rapport

L'artefact `mission036-publication-<run>-<attempt>` contient le manifeste figé,
le journal des lots et `publication-report.json`. Le rapport final est aussi
ajouté dans `reports/evidence/mission029/publication/<run>-<attempt>/` sur
historical-data, avec révision du code et révision des données contrôlées.

Les décomptes `published`, `missing` et `mismatched` sont disjoints et leur somme
égale `expected`. Ils sont donnés globalement et par
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
Le recoupement composition/joueurs ne suffit pas à prouver tous les critères :
Abs exige aussi les minutes historiques nécessaires. Une minute inconnue reste
inconnue, y compris pour un remplaçant sans note ; elle n'est jamais convertie
en zéro. Les taux finaux et leurs motifs doivent être lus dans `coverage.csv`.

### Compatibilité des reçus 027 historiques

Le premier dispatch `39395579612` a refusé une référence (`REFERENCE_SCOPE`),
avant toute projection publiée. Le producteur antérieur à `48a93765` conservait
le chemin absolu du runner dans `partitions[].path` :
`<home>/runner/work/robin-stades-ng/robin-stades-ng/artifacts/historical-deep/mission027/`
(racine home Linux du runner historique ; aucun accès au système de fichiers).
Cette seule racine connue est retirée pour la mission 027 ; le chemin obtenu
reste soumis au contrat canonique et doit correspondre exactement à la clé R2
attestée. Aucune lecture du chemin local du reçu, aucun alias libre, aucun
assouplissement du hash ou du holdout. Le test couvre aussi les racines étrangères
et la traversée de répertoires.

### Arbre Git partiel et inventaire initial effectivement observé

Le dispatch `39396417715` a vérifié les reçus R2 et les objets sélectionnés déjà
publiés : 126 756 références, 16 522 conformes, 110 234 absentes, zéro hash
contradictoire. Il a ensuite échoué avant le premier push. Le test de clone
partiel reproduit l'échec de `write-tree`, puis prouve le correctif
`write-tree --missing-ok` jusque dans un push réel vers le dépôt synthétique.
Les entrées héritées conservent les identifiants du parent distant ; chaque
nouvel objet a été vérifié SHA-256 puis écrit par `hash-object -w`. Les blobs hors
périmètre restent absents après le push, sans lecture holdout. Cette option
n'autorise ni entrée nouvelle arbitraire ni publication d'un objet non vérifié.
Les erreurs Git gardent les derniers compteurs et exposent seulement le nom
fixe de l'opération et son code de sortie, sans stderr susceptible d'être secret.
