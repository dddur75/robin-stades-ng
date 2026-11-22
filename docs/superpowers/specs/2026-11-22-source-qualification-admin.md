# Suivi admin des qualifications récentes

L’admin actuel montre le journal initial des57connecteurs, mais les contrôles natifs récents restent dans les preuves de travail. Ajouter un panneau daté en lecture seule à /expert/admin-collecte, après le résumé des pronostics et avant le catalogue. Le besoin admin et le travail autonome sont déjà autorisés par David.

## Contrat

- Un instantané local structuré, limité à128KiB et50résultats, contient seulement labels, dates, états, compteurs mesurés, périmètre, prochaine étape et claim_id. Aucun pronostic, nom de personne, corps source ou secret.
- Les valeurs null restent « Non mesuré ». Zéro signifie réellement mesuré à zéro. Chaque résultat garde sa date et ses références.
- Le panneau distingue source lisible sans candidat, contrôle technique échoué et preuve manquante. Il ne déclare aucune source active et ne change aucun grant, registre, tâche, budget ou donnée de collecte.
- L’endpoint local refuse méthodes, origines et clients non locaux avec le garde existant. Fichier absent, invalide ou surdimensionné :503. L’endpoint hébergé reste indisponible. Aucun appel aux fournisseurs.
- La couverture est explicitement partielle : il s’agit de contrôles ciblés, pas du classement exhaustif des sources du classeur.
- Réutiliser cartes, dates Paris et tables existantes ; actualisation manuelle du seul instantané. Préserver les anciennes preuves et les huit verrous.

## Vérification

Tests ciblés pour inconnus vs zéros, validation/whitelist, fichier absent/invalide/trop gros, refus réseau/méthode/origine et un endpoint réel local. Typage/lint du domaine, build et budget JS. Recette navigateur du panneau réellement affiché et état503, sans requête externe. Revue C3 indépendante et C4 des données avant copie runtime.
