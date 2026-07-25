# Root cause du modèle post-lineup

Sur 611 fixtures exactement appariées, le post-lineup dégrade la Log Loss de
+0,03178 face au pré-lineup; CI 95 % [0,01557 ; 0,04784], probabilité
d’amélioration 0. La dégradation est donc compatible avec une vraie perte, pas
avec un simple bruit d’échantillonnage.

Causes testables : un seul fold de développement utilisable sur ce dataset,
composition simulée plutôt que snapshot réellement archivé, redondance avec la
force pré-lineup, support joueur inégal et variance accrue. Le modèle reste
auditable mais rejeté pour promotion. Aucun artefact post-lineup n’est présenté
comme disponible avant annonce officielle.
