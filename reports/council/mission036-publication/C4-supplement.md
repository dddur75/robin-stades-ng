# Complément C4 avant dispatch

Relecture indépendante en lecture seule, 20 octobre 2026. Les changements de
fetch explicite `--refetch --no-filter`, de reprise depuis la ref distante
filtrée, de concurrence prioritaire du rattrapage et le test de clone partiel
réel ont été relus. Aucun P0/P1 ni blocage du dispatch n'est identifié.

Les wants restent limités aux SHA des chemins attendus hors holdout ; le test
vérifie qu'un blob non sélectionné reste absent. La reprise ne réaffecte que
la ref locale ; le push reste sans force. La preuve GitHub réelle AUT 2019
rapporte un SHA-256 identique au reçu B-calendars figé.

PASS_AND_HOLD maintenu pour l'implémentation. Une livraison complète demande
encore le rapport distant COMPLETE et un inventaire de reçus stable. Aucune
écriture de fichier ni opération externe n'a été effectuée par C4.

Le complément d'hydratation/recalcul hors ligne et les deux phrases de rapport
ont également été relus : aucun P0/P1 identifié. La sélection suit FAMILIES et
les joueurs par fixture, exclut 2025 avant lecture et transmet le SHA source
immuable via GIT_ALTERNATE_OBJECT_DIRECTORIES. Le calcul ne reçoit aucun accès
GitHub/R2/fournisseur/Neon. Les formules et règles temporelles sont inchangées.
Le budget global du job inclut aussi le recalcul ; sa réussite et l'artefact
final doivent être inspectés avant de déclarer la livraison complète.

C4 followup after dispatch 39395579612 (read-only publication_review) : aucun
P0/P1 ni blocage pour le prochain dispatch autorisé. Le producteur pré-48a93765
publiait bien `partition['path']` absolu et une clé R2 relative. L'alias exact,
réservé à 027, conserve regex canonique, clé R2 exacte, SHA64 et exclusion holdout.
43 tests publication/workflow/reprise passent indépendamment en 2,02 s. La
compatibilité annoncée dans la revue initiale concernait les producteurs actuels ;
les anciens reçus exigent cet alias maintenant testé. Exhaustivité R2 à vérifier.
C4 a également revu l'optimisation d'index : le format nul `100644 SHA\tpath\0`
est valide ; une mise à jour par lot conserve contrôles de conflits, noop et CAS.

C4 delta après le dispatch 39396417715 : aucun P0/P1 ; 43 contrôles indépendants
passent en 1,98 s. `write-tree --missing-ok` préserve les IDs du parent distant ;
chaque ajout est écrit par hash-object avant l'index et les références
sélectionnées restent vérifiées SHA-256. Le test de clone partiel pousse l'ajout
et confirme qu'un blob non sélectionné reste absent. L'assemblage de l'alias
historique conserve exactement les octets acceptés. C4 a signalé un P2 sur le
diagnostic d'échec du clone initial (absence de --git-dir) : C0 l'a gardé et ajouté
un test de régression ; les 60 contrôles ciblés passent après correction.

### Premier passage effectif et contrôle intermédiaire (20 octobre, avant reprise)

C4 a recoupé hors réseau les copies du rapport et du journal avec le ZIP de
l'artefact 12262822837 (SHA-256
`96c4b82fbb9e8466e4492ad58b43a327e6171e5ef91cf6411729d807c314d5db`).
Les 118 lots ajoutent 117 868 objets aux 17 255 déjà publiés : 135 123 / 135 124,
un seul manque `R2_READ_FAILED` pour MEX2019 fixture293438, zéro hash discordant.
Rapport et journal sont conservés dans `PUBLICATION-PASS-1.json` et
`PUBLICATION-PASS-1-BATCHES.jsonl`. La tentative suivante reste nécessaire.

C4 a également lu uniquement les 237 calendriers normalisés déjà présents dans
le cache Git, protocoles et lazy fetch refusés. Chaque SHA-256 concorde avec le
manifest des reçus ou l'inventaire antérieur : 75 687 lignes/IDs uniques,
70 084 IDs cibles présents, zéro absent. La preuve est
`calendar-id-audit.json`. Elle établit la présence des identifiants, sans
anticiper la validation des contextes ou la couverture calculée.

Le contrôle non vacuant des critères Abs/XI a été renforcé après une objection
P2 de C4 : la liste `non_null` de chaque ligne d'audit doit correspondre aux
valeurs Parquet effectivement hachées. C4 confirme la correction. Les trois
tests d'artefacts de la livraison antérieure passent ; le nouveau test de
réception ≥ 90 % et Abs/XI attend les sorties réelles du recalcul.

### Budget du passage ordinaire après préparation lente

C4 confirme le défaut reproduit par horloge simulée : 301 s de préparation
consommaient les 300 s du mode ordinaire avant le premier GET. Le correctif
affecte uniquement ce mode : 300 s de transfert après préparation, sous le
timeout global inchangé du job. Le mode catchup conserve exactement son calcul
de deadline globale ; l'exécution réelle sur `1416488b` n'est pas modifiée.
Le test paramétré distingue publication d'un objet en mode normal et absence
de GET après expiration en mode catchup. Rouge : un échec normal ; vert :
63 tests ciblés, Ruff et Bandit. Revue C4 du diff : aucun P0/P1 introduit.

C4 a aussi recoupé les deux manifests hors réseau : les 135 124 références de
la tentative1 sont toutes identiques dans l'inventaire élargi à 144 071.
Seuls 8 946 objets C et un reçu ont été ajoutés par le passage indépendant de
main. Aucune ancienne preuve n'a été remplacée ou supprimée.

### Passage 2, passage 3 et redesign E1 de reprise des erreurs de lecture

C4 a vérifié hors réseau les deux ZIP et leurs copies JSON/JSONL :
passage2, artefact12273085198, SHA-256
`f089a21f2a530a5e2c1b1f5535e44d977a207ce46c3f09351dbfeaf3715ec5f5`,
6 000 ajouts confirmés, 142 027 / 144 071, 2 044 manquants, push exit1 dont la
sous-cause n'est pas observée. Le lot local non confirmé n'est pas compté.
Passage3, artefact12272477063, SHA-256
`9c9a3dc3b258d6f57e6f223b9cd2071f526be6ef99343282bf36a7a094c8411d`,
2 043 ajouts confirmés, 144 070 / 144 071, un `R2_READ_FAILED` SP2/2024
fixture1217550. Les pushes de ce passage réussissent. Aucun mismatch.

Après ce second cas d'erreur de lecture, retour E1 et redesign avant nouveau
lancement : aucune nouvelle tentative identique sur141. C4 contre-vérifie la
ronde supplémentaire bornée, réservée au catchup, à BLOCKED et à des issues
non vides toutes `R2_READ_FAILED`, dans le temps restant. Le flag global est
consommé avant la ronde et persiste si le manifest croît. Les objets publiés
passent de nouveau la réconciliation Git ; ils ne sont pas relus dans R2.
Aucun retry d'objet absent, de hash contradictoire, de push ou d'état PARTIAL.
Deux tentatives SDK par GET, au plus quatre tentatives réseau par objet
sélectionné ; plafond global9 600s et huit lecteurs inchangés. Une erreur
persistante finit BLOCKED. Le marqueur JSONL et le compteur du rapport gardent
la trace de cette ronde, y compris au retour pour changement d'inventaire.

Rouge : deux tests de récupération/persistance échouent avant correctif.
Vert :71 tests ciblés, Ruff et Bandit. C4 inspecte le diff et les tests
(horloge, erreurs persistantes, absences, hashes, issues vides, PARTIAL et
nouveau reçu après récupération). Aucun P0/P1 ; PASS_AND_HOLD pour un seul
nouveau dispatch après traçabilité REDESIGN+DECISION, dans l'autorisation
utilisateur existante. Revue finale des critères encore en attente.
