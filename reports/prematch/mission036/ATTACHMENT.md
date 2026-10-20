## Pourquoi 25 % seulement

**17 433 / 70 084 = 24,87 %** désigne le rattachement à un contexte fournisseur
(coup d'envoi et identités des deux équipes), pas le taux de collecte B ni le taux
de critères non nuls. Les 70 084 `fixture_id` sont présents et uniques dans la
population et dans les sorties ; les 52 651 lignes sans contexte gardent date et
noms du mapping, sans inventer les identités fournisseur.

**Les 52 651 pertes proviennent toutes de calendriers non publiés** dans le
snapshot `fac718f36d0b8e178374d5a8384c1b3cc871f135` : 29 ligues × 6 saisons
2019–2024, soit 174 partitions manquantes. Le reçu `B-calendars` du run
`39152147826-1` atteste 200/200 requêtes calendrier complètes, sans manque ni
incertitude, et référence les 200 Parquet avec leur clé R2 et SHA-256. Seulement
26 de ces chemins existent dans l'inventaire : ARG (8), AUT (6), B1 (6), BRA (6) ;
les 26 hashes concordent. Les 174 absents correspondent exactement aux 174
cellules ligue-saison sans contexte. Les 37 autres partitions de fixtures publiées
apportent notamment les calendriers des cinq grands championnats et l'historique.

Le compte se ferme : **9 647** matchs des cinq grands championnats + **7 786**
ARG/AUT/B1/BRA = **17 433** rattachés ; **52 651** des 29 autres ligues = aucun
rattachement. Il n'y a **aucun fichier calendrier publié vide**, aucune perte de
contexte par `fixture_id` absent de la population et aucun conflit de fixtures
signalé par le chargeur. Les archives de détail Ligue 1 et les fichiers joueurs
vides causent d'autres manques, pas cette perte de 52 651 contextes.

Le mécanisme de publication explique le décalage stockage/publication :
`scripts/publish_mission029.py` ne publie que des chemins nouveaux, parcourt les
receipts puis les projections R2 et s'arrête à **1 000 fichiers ou 300 secondes**
par passage. Il ne garantit pas que tous les objets déjà collectés soient
visibles dans `historical-data`. Les reçus ne permettent pas de déterminer lequel
de ces deux plafonds a arrêté chaque passage ; aucun accès R2 n'a été fait pour
prétendre vérifier l'existence actuelle des objets.

| Vérification indépendante | Résultat au snapshot |
|---|---:|
| Calendriers du reçu B-calendars | 200 référencés ; 26 publiés ; **174 non publiés** |
| Événements B complets, population entière | 66 772 ; 8 145 IDs complets avec Parquet `events` publié ; **58 627 sans ce Parquet** |
| Parmi les 52 651 contextes absents | **50 285** ont déjà un résultat B complet attesté |
| Dernier lot B seulement | 2 878 partitions référencées ; 132 publiées ; **2 746 non publiées** |
| Dernier lot C seulement | 6 082 partitions référencées ; 653 publiées ; **5 429 non publiées** |
| Stock C complet attesté | **7 283 / 70 084** ; reçu PARTIAL, tranche arrêtée ; ne pas assimiler le reste à des payloads collectés |
| Parquet `events` publiés, tous états | 8 631 fichiers, dont **1 vide** ; 486 IDs ne sont pas complets selon B |
| Parquet `players` par fixture publiés | 1 070 fichiers, dont **255 vides** ; 247 lignes de détail rejetées |
| Détails Ligue 1 sans clé de fixture exploitable | **40 561 lignes** : 32 383 événements + 4 100 compositions + 4 078 statistiques joueurs |

Le calcul des 58 627 utilise la population figée moins les 2 781 manques B et
531 incertitudes, puis soustrait les IDs complets publiés. Cette soustraction
n'est pas applicable au reçu C, qui ne couvre pas encore toute la population.
Les 40 561 sont des **lignes, pas des matchs** ; le calendrier Ligue 1 rattache
déjà ses 2 419 matchs. Elles nécessitent l'index `raw_payload_hash → fixture_id`
issu des observations originales, pas une jointure par ordre de ligne.

### Actions pour atteindre 90 % de rattachement

Il faut **63 076** contextes au minimum, donc **45 643 supplémentaires**.
Le chemin proposé ne nécessite aucun nouvel appel fournisseur :

| Action, à réaliser séparément de cette PR | Gain / contrôle | Coût fournisseur ; autre coût |
|---|---|---|
| Vérifier puis publier les **174** calendriers déjà référencés par B-calendars, en traitant d'abord les calendriers plutôt que toute la file de détails | Réservoir de **52 651** contextes ; potentiel **100 %** sous réserve de disponibilité des objets et validation des IDs | **0 appel** ; 174 lectures R2 et écritures Parquet/index, plus exécution Actions/Git ; pas de coût monétaire chiffrable sans tarifs |
| Si une projection manque mais le brut immuable est présent, renormaliser uniquement les calendriers concernés ; conserver `fixture.id`, kickoff et IDs des équipes | Même gain, sans double comptage ; contrôler les hashes, le périmètre hors holdout et la population figée | **0 appel** ; lecture des bruts/index, CPU de normalisation et publication |
| Réinventorier le nouveau snapshot, contrôler les 70 084 IDs puis recalculer couverture et audit décalé ; accepter seulement si ≥ 63 076 contextes | Prouve le franchissement de **90 %**, sans promettre 90 % de critères calculables | **0 appel** ; calcul local/Actions ; aucune écriture Neon requise |
| Publier séparément les détails B/C déjà stockés et l'index de rattachement Ligue 1, partitionnés hors 2025 | Améliore les critères ; **0 contexte supplémentaire** une fois les calendriers publiés ; C reste incomplet | **0 appel** pour le stock existant ; lectures R2 et export d'index ; ne pas réinterroger les réponses vides/incertaines |
| Seulement si brut **et** projection sont réellement absents : autoriser une collecte ciblée des calendriers manquants | Solution de dernier recours ; non nécessaire au vu du reçu actuel | **1 appel par requête ligue-saison réellement absente, au plus 174** pour ces calendriers ; autorisation/plafond/receipt préalables, jamais un rejeu général |

Aucune de ces actions de publication ou collecte n'est exécutée ici. Les reçus
attestent les écritures historiques, pas la disponibilité actuelle de R2.
Les tirs horodatés, règles de cumul et calendriers toutes compétitions restent
soumis à leurs preuves propres : 90 % de rattachement n'est pas 90 % de couverture
des critères. Décompte inspectable : `ATTACHMENT-AUDIT.json` et
`attachment-coverage.csv` dans `reports/prematch/mission036/` (claim
`DATA.MISSION036.PREMATCH.V1`).

### Répartition exacte des 52 651 contextes absents

| Ligue | 2019 | 2020 | 2021 | 2022 | 2023 | 2024 | Total manquant |
|---|---:|---:|---:|---:|---:|---:|---:|
| CHN | 121 | 156 | 180 | 300 | 240 | 240 | 1237 |
| D2 | 306 | 306 | 306 | 306 | 306 | 306 | 1836 |
| DNK | 243 | 192 | 192 | 193 | 193 | 192 | 1205 |
| E1 | 552 | 552 | 552 | 552 | 552 | 552 | 3312 |
| E2 | 400 | 552 | 552 | 552 | 552 | 552 | 3160 |
| E3 | 440 | 552 | 552 | 552 | 552 | 552 | 3200 |
| EC | 451 | 477 | 506 | 552 | 552 | 552 | 3090 |
| F2 | 280 | 380 | 380 | 379 | 379 | 306 | 2104 |
| FIN | 87 | 134 | 164 | 166 | 167 | 167 | 885 |
| G1 | 240 | 240 | 240 | 240 | 238 | 233 | 1431 |
| I2 | 378 | 379 | 380 | 380 | 380 | 380 | 2277 |
| IRL | 72 | 90 | 181 | 180 | 180 | 181 | 884 |
| JPN | 156 | 306 | 380 | 306 | 306 | 380 | 1834 |
| MEX | 274 | 342 | 341 | 342 | 339 | 340 | 1978 |
| N1 | 232 | 306 | 306 | 305 | 306 | 306 | 1761 |
| NOR | 139 | 240 | 240 | 242 | 242 | 242 | 1345 |
| P1 | 306 | 306 | 306 | 306 | 306 | 306 | 1836 |
| POL | 296 | 240 | 306 | 305 | 306 | 306 | 1759 |
| ROU | 262 | 320 | 316 | 320 | 320 | 315 | 1853 |
| RUS | 236 | 240 | 244 | 244 | 244 | 240 | 1448 |
| SC0 | 179 | 228 | 228 | 228 | 228 | 228 | 1319 |
| SC1 | 137 | 135 | 180 | 180 | 180 | 180 | 992 |
| SC2 | 139 | 109 | 180 | 180 | 180 | 180 | 968 |
| SC3 | 137 | 110 | 180 | 180 | 180 | 180 | 967 |
| SP2 | 462 | 462 | 462 | 462 | 462 | 462 | 2772 |
| SWE | 138 | 242 | 242 | 242 | 240 | 242 | 1346 |
| SWZ | 181 | 182 | 181 | 182 | 230 | 228 | 1184 |
| T1 | 306 | 420 | 380 | 313 | 379 | 341 | 2139 |
| USA | 208 | 322 | 470 | 489 | 519 | 521 | 2529 |
| **Total** | 7358 | 8520 | 9127 | 9178 | 9258 | 9210 | **52651** |
