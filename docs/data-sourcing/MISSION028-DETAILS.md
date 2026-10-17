# Mission 028 — compositions puis statistiques

Cette suite dépend de la PR #103. La correspondance réelle est livrée dans la PR #105 : 60 437 identifiants
confirmés. Cette PR est empilée sur #105 et attend la relecture indépendante.

Entrées figées : `configs/execution/mission028-mapping.csv` (sortie exacte de la
phase 1) et `mission028-mapping.json`, contenant `source_sha256` et
`mapping_sha256`. Chaque ligne est comparée à la population source, avant R2 ou
HTTP. Une table manquante ou altérée arrête le prévol.

Workflow 71 existant : `execute=true`, `details_family=lineups` pour la phase 2,
puis `details_family=statistics` pour la phase 3. Le prévol est unique avant les
seize workers. Chaque worker prend des ligues disjointes, avec une limite de
95 minutes ; le transport interdit de dépasser minuit UTC ou les 110 minutes
de preuve. La concurrence du workflow reste inchangée.

Les 69 750 slots quotidiens sont partagés par les deux familles et acquis par
écriture conditionnelle R2 ; 200 places sont conservées pour les calendriers,
50 pour les prévols (49 nouveaux, plus le prévol initial). La liste liée au
manifeste contient exactement 60 437 identifiants ; les deux familles et les
200 calendriers laissent 1 126 prévols au plafond global de 122 200 appels.
Nous en gardons au plus 926 (le premier et 925 nouveaux), soit 122 000
appels au maximum et encore 200 places de marge pour toute la mission.
Une réservation incertaine consomme le budget et n’est jamais rappelée.

Les partitions achevées sont reprises à l’identique depuis R2. Un groupe
interrompu reprend ses reçus existants avant d’appeler un nouvel identifiant.
Les réponses vides et incomplètes restent dans le reçu ; elles ne sont pas
converties en formations ou en statistiques fictives.

Recette : ≥ 95 % de compositions (deux équipes, formation, onze titulaires
distincts), ≥ 90 % de statistiques des deux équipes. Les xG restent absents si
le fournisseur ne les donne pas. Aucun appel n’est effectué depuis la session.

Le manifeste de la liste est lié immuablement dans R2 avant le premier prévol.
Un autre manifeste est refusé avant tout client fournisseur : le plafond total
reste valable à travers toutes les reprises, même sur plusieurs jours UTC.
Les lignes des rencontres argentines de coupe portent la ligue API 1032 en
2023/2024 ; leurs partitions logiques restent sous ARG.
