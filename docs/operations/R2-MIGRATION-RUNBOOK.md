# Runbook de migration R2

1. Exécuter `30 - Migration object storage` avec `execute=false`.
2. Vérifier fichiers, octets, `deletions=0` et `double_write=true`.
3. Créer un bucket Cloudflare R2 privé.
4. Ajouter `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` et
   `R2_BUCKET_NAME` aux secrets GitHub.
5. Exécuter avec `execute=true` et un petit `max_files`.
6. Comparer hashes, volumes et replay avant d’augmenter le lot.

Ne jamais rendre le bucket public, exposer les secrets dans le Cockpit, ni
supprimer `historical-data` avant validation explicite du rapport.
