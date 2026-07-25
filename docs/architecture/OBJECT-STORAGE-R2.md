# Object Storage R2

L’adaptateur `ObjectStorageAdapter` cible une API S3 compatible et un bucket
privé. Il fournit upload idempotent, téléchargement, vérification SHA-256,
replay et migration dry-run. La suppression n’est pas exposée.

Pendant une migration, `historical-data` reste le pont de sécurité et R2 reçoit
une double écriture. Git/Neon conservent manifests, hashes, index, checkpoints
et résultats synthétiques. Les objets volumineux restent inchangés jusqu’à
validation des volumes, hashes, double lecture et replay.

Seuils : optional sous 600 MB avec projection centrale sous 750 MB; recommended
à partir de 600 MB ou 750 MB projetés; required à partir de 700 MB réels ou
900 MB projetés.
