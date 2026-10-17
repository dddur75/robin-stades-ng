# Mission 028 — reprises sous plafonds UTC

Le seul workflow 71 planifie la collecte depuis `main` après intégration par
Qualité. Son cron `17 */2 * * *` démarre une tranche toutes les deux heures UTC.
Aucun autre workflow, relais, dispatch GitHub ou appel depuis une session.
L’exception applicable est celle de David dans qg#76.

Dans le même job, `scripts.mission028_resume` valide d’abord les empreintes de
la population et de la table, puis lit les contrôles durables R2. Seul READY
lance les détails avec la famille choisie : compositions jusqu’aux seize reçus
terminaux, puis statistiques. DONE, BUDGET, PAUSED et HOLD terminent proprement
sans appel fournisseur et sans upload d’artefact vide. Le cron reste présent ;
DONE arrête la collecte, sans demander de permission de désactivation.

Un déclenchement planifié ne lance ni les bundles historiques, ni la phase 1,
ni la publication de leur décision provider. Les modes manuels conservent leurs
conditions. Les permissions de 71 (`contents: read`, `actions: read` déjà hérité de la 027) et son groupe de concurrence
restent identiques à la base de la PR. La planification ne reçoit aucune clé
fournisseur ; celle-ci est limitée à l’étape de détails effectivement autorisée.

Les seize workers traitent des ligues disjointes à ≤ 8 requêtes/s cumulées.
La preuve expire après 110 minutes ; un lot s’arrête après 95 minutes au plus ou
à minuit UTC. Les identités des réservations et reçus reposent sur la requête et
la rencontre, jamais sur le worker ; les réservations incertaines ne sont pas
rappelées. Une expiration reprend au prochain cron. Une erreur inattendue pose
une pause durable liée à la révision ; un plafond quotidien attend le prochain
jour UTC, et le plafond total demeure bloquant.

Le module partagé de #104 réserve 69 750 détails/jour, une marge de 200 calendriers
et au plus 50 prévols (49 nouveaux plus l’original), soit ≤ 70 000 appels/jour UTC.
Les 925 nouveaux prévols globaux donnent avec les 60 437 IDs figés un majorant
200 + 2 × 60 437 + 926 = 122 000 ≤ 122 200. Réserve fournisseur : ≥ 5 000.
Contrôles, prévols et reçus publics restent append-only dans R2.

DONE signifie cibles parcourues pour les deux familles ; les couvertures et
écarts doivent encore être vérifiés (95 % de compositions, 90 % de statistiques)
avant recette et publication. Les deux lots existants documentent 6 738 appels.
Les 5 510 compositions complètes du second lot incluent le cache du premier ;
les 19 Parquet vérifiés représentent 3 747 matchs, dont 3 109 complets. Aucune
statistique collectée à ce stade : `DATA.MISSION028.LINEUPS_SLICE2.V1`.
La correction de planification reste soumise à Claude et à Qualité.
