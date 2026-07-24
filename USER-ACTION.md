# Action utilisateur

ACTION UNIQUE : créer un projet PostgreSQL chez Neon, puis enregistrer sa chaîne
de connexion complète dans le secret GitHub Actions `DATABASE_URL` du dépôt
`dddur75/robin-stades-ng`.

Le plan Free suffit pour démarrer le burn-in sans achat. Le volume saisonnier
estimé est de 0,4 à 0,8 Go ; si la limite gratuite de 0,5 Go devient trop étroite,
passer au plan Launch, estimé autour de 15 USD/mois pour une petite charge
intermittente. Ne jamais coller cette URL dans un fichier, une issue ou un log.

Après création du secret, le prochain workflow shadow appliquera automatiquement
les migrations Alembic et activera la double écriture PostgreSQL + `shadow-data`.
`API_FOOTBALL_KEY` reste optionnelle et ne fait pas partie de cette action.
