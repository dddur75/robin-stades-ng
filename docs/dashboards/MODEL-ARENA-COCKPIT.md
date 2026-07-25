# Model Arena dans le Cockpit

La vue privée affiche le gel de baseline, protocole externe, familles testées,
prédictions, delta de Log Loss, CI 90/95 %, probabilité de supériorité,
Strategy Lab V2, appels fournisseur, quota et candidats live.

`COCKPIT_BUILD_SUCCESS`, `COCKPIT_ARTIFACT_PUBLISHED` et
`COCKPIT_PRIVATE_DEPLOYED` restent des statuts distincts. Le snapshot ne
contient ni URL Neon, ni secret, ni payload privé. Une arène non exécutée
affiche `NOT_RUN`; elle ne fabrique aucune donnée de démonstration.
