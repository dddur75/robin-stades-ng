# Politique `ACCELERATED_SAFE`

Le planificateur recalcule toutes les deux heures `max_calls`, `max_tasks`,
`request_rate`, `batch_size` et `next_run_at`. Il utilise le quota restant, la
réserve de 5 000 appels, le coût et la durée observés, les erreurs, les 429, la
qualité temporelle et le stockage.

Le pilote mesure 1 354 appels en 197,683 s, soit 0,146 s/appel, 25,074
appels/tâche de plan initiale, 4,368 appels/fixture, 8,027 lignes/appel,
1 857 octets compressés/appel et 28,611 payloads/tâche initiale. Les taux
d’erreur et d’endpoint indisponible observés sont nuls ; le replay a un taux de
cache de 100 % et ne consomme aucun appel.

La cible est 30 000 appels/jour, jamais le quota complet de 150 000. Chaque run
est plafonné par sa part quotidienne, 110 minutes et la réserve. Arrêts
explicites : quota protégé, durée maximale, aucune tâche, erreurs > 5 %, 429,
qualité temporelle critique ou seuil de stockage.

Les reprises HTTP utilisent backoff exponentiel avec jitter, débit configurable
et circuit breaker. Une indisponibilité permanente devient
`SKIPPED_UNAVAILABLE` ou `QUARANTINED`; elle n’est pas rappelée indéfiniment.

La couverture ne se déclenche pas en parallèle de chaque push : elle reste
hebdomadaire et manuelle. Le backfill est ainsi le seul run historique
automatique susceptible d’attendre le verrou, ce qui évite le remplacement
d’un run GitHub en attente.
