# Object Storage R2

L’adaptateur `ObjectStorageAdapter` cible une API S3 compatible et un bucket
privé. Il fournit upload idempotent, téléchargement, vérification SHA-256,
replay et migration dry-run. La suppression n’est pas exposée.

Pendant une migration, `historical-data` reste le pont de sécurité et R2 reçoit
une double écriture. Git/Neon conservent manifests, hashes, index, checkpoints
et résultats synthétiques. Les objets volumineux restent inchangés jusqu’à
validation des volumes, hashes, double lecture et replay.

Le client Cloudflare utilise l'endpoint global
`https://<R2_ACCOUNT_ID>.r2.cloudflarestorage.com` avec
`region_name="auto"`. Aucune juridiction `.eu.` n'est codée. Seuls les codes
S3 `404`, `NoSuchKey` et `NotFound` sont interprétés comme une absence lors du
`head_object`. Les erreurs `401`, `403`, réseau ou service restent bloquantes.

Pour chaque fichier sélectionné, la migration calcule le SHA-256 et la taille
locale. Un objet dont la métadonnée `sha256` correspond est tout de même relu
avant d'être classé `replayed`. Un objet nouveau ou divergent est envoyé avec
la métadonnée, puis relu avant d'être classé `uploaded`. La taille et le hash
des octets relus doivent correspondre.

Les rapports `storage/r2-migration-*.json` sont exclus du périmètre pour
éviter l'auto-inclusion. Le lot est cumulatif : 25 sélectionne les 25 premiers
fichiers, 250 les 250 premiers, et une borne supérieure au total vérifie tout
le périmètre.

Le rapport durable contient les volumes source et sélectionnés, les uploads,
replays, vérifications distantes, écarts de hash et de taille, objets
manquants, mutations source, suppressions, preuve de double écriture,
complétude, statut, hash non sensible du bucket et horodatages. `complete=true`
exige une vérification distante de tout le périmètre, zéro écart et des sources
strictement inchangées. `deletions` reste toujours nul et aucune méthode de
suppression n'existe dans l'adaptateur.

Seuils : optional sous 600 MB avec projection centrale sous 750 MB; recommended
à partir de 600 MB ou 750 MB projetés; required à partir de 700 MB réels ou
900 MB projetés.
