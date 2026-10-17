# Mission 028 — reprises sous plafonds UTC

Le workflow dédié `mission028-daily.yml` orchestre le workflow 71 existant.
Le cron 00:17 UTC et le dispatch de ce nouveau fichier ne sont disponibles
qu’après intégration sur la branche par défaut par Qualité. Avant cela, lancer
71 sur `tache-028-reprises`, `execute=true`, `details_family=lineups` ; après
les compositions, utiliser `statistics`. Aucune collecte depuis la session.

Les seize workers prennent des ligues disjointes, avec une cadence cumulée
≤ 8 requêtes/s. La preuve expire après 110 minutes ; chaque lot s'arrête au
plus tard après 95 minutes ou à minuit UTC. Les réservations et reçus existants
restent valables après un changement de nombre de workers : leur identité
repose sur la requête et la rencontre, jamais sur le worker.

Le planificateur lit uniquement les contrôles R2 et vérifie d’abord les hashes
de la population et de la table. Il sélectionne les compositions jusqu’aux
seize reçus terminaux, puis les statistiques. Une fin de lot pour expiration
reprend sans rappeler les réservations incertaines. Une erreur inattendue
pose une pause durable liée à la révision du code. Un plafond quotidien attend
le jour UTC suivant ; le plafond total demeure bloquant. Au plus vingt lots
s’enchaînent pour une invocation quotidienne ; HOLD exige une reprise explicite
ou la prochaine invocation prévue. L’annulation du workflow empêche son relais.

Les contrôles, prévols et reçus publics sont append-only dans R2. Les jobs
planification et relais ne reçoivent aucune clé fournisseur. Seul le relais du
workflow dédié possède `actions: write`, pour relancer puis désactiver uniquement
`mission028-daily.yml`. Les permissions des collecteurs historiques sont conservées.

DONE signifie que toutes les cibles ont été parcourues pour les deux familles.
Il arrête le cron ; il ne valide pas les seuils de qualité. Les couvertures et
écarts des reçus doivent toujours être vérifiés (95 % et 90 %) avant recette.

Observation initiale : run `38999517118`, 577 appels de compositions, 551 réponses
complètes ; arrêt à l’expiration de la preuve, aucune partition encore achevée.
Cette observation partielle ne mesure pas la couverture des 60 437 cibles.
Preuve : `DATA.MISSION028.REPRISES.V1`, revue indépendante en attente.
