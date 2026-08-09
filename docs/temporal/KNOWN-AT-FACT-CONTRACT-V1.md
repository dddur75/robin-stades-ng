# Contrat Known-At Fact V1

Robin Chronos distingue l'heure de l'événement de l'heure où Robin a réellement
pu connaître l'information. Par défaut, `known_at = response_received_at`. Une
preuve de disponibilité plus restrictive peut retarder `known_at`, jamais
l'antidater. Un timestamp fournisseur reste une information de fraîcheur et ne
remplace pas l'heure de réception Robin.

Un fait est `ON_TIME` lorsque `known_at <= cutoff_at` et
`cutoff_at < kickoff_at`. L'égalité au cutoff est explicitement admissible pour
la décision scientifique. Le scheduler historique continue d'affecter les
captures à des fenêtres demi-ouvertes afin d'éviter qu'une même capture ne soit
comptée deux fois entre H-2 et `NEAR_KICKOFF`.

Les faits après cutoff sont conservés comme `LATE_FOR_CUTOFF`; ceux connus à ou
après kickoff sont `POST_KICKOFF_ONLY`; l'absence d'heure fiable est
`KNOWN_AT_UNKNOWN`. Aucun de ces trois états n'entre dans une vue stricte.

Les corrections sont append-only. Un doublon exact est idempotent; une valeur
différente crée une nouvelle version qui référence `supersedes_fact_id`. Les
payloads bruts restent dans R2. PostgreSQL ne conserve que les identifiants,
hashes, timestamps, classes et rôles nécessaires au replay et à l'audit.

H24 est l'alias contractuel de `J-1`, H6 celui de `H-6`. Les données historiques
ne sont jamais renommées ou reclassées rétroactivement.
