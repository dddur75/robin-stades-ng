# Mission 028 — compositions puis statistiques

Cette suite dépend de la PR #103. La PR reste empilée et en brouillon tant que
la correspondance réelle et sa recette ne sont pas livrées.

Entrées figées : `configs/execution/mission028-mapping.csv` (sortie exacte de la
phase 1) et `mission028-mapping.json`, contenant `source_sha256` et
`mapping_sha256`. Chaque ligne est comparée à la population source, avant R2 ou
HTTP. Une table manquante ou altérée arrête le prévol.

Workflow 71 existant : `execute=true`, `details_family=lineups` pour la phase 2,
puis `details_family=statistics` pour la phase 3. Le prévol est unique avant les
quatre workers. Chaque worker prend des ligues disjointes, avec une limite de
95 minutes ; le transport interdit de dépasser minuit UTC ou les 110 minutes
de preuve. La concurrence du workflow reste inchangée.

Les 69 800 slots quotidiens sont partagés par les deux familles et acquis par
écriture conditionnelle R2 ; 200 places sont conservées pour les calendriers.
Chaque famille a au plus 61 000 identifiants uniques et une réservation durable
par identifiant : le total est donc borné à 200 + 61 000 + 61 000 = 122 200.
Une réservation incertaine consomme le budget et n’est jamais rappelée.

Les partitions achevées sont reprises à l’identique depuis R2. Un groupe
interrompu reprend ses reçus existants avant d’appeler un nouvel identifiant.
Les réponses vides et incomplètes restent dans le reçu ; elles ne sont pas
converties en formations ou en statistiques fictives.

Recette : ≥ 95 % de compositions (deux équipes, formation, onze titulaires
distincts), ≥ 90 % de statistiques des deux équipes. Les xG restent absents si
le fournisseur ne les donne pas. Aucun appel n’est effectué depuis la session.
