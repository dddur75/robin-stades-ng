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
