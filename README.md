# Robin des Stades — registre shadow-data

Branche de données orpheline et append-only. Elle ne contient aucun code
applicatif et sert de pont durable tant que PostgreSQL distant n’est pas
configuré.

- `objects/` : payloads bruts compressés, adressés par SHA-256 ;
- `bundles/` : observations et objets normalisés par run ;
- `manifests/index.jsonl` : journal de contenu, hashes et couverture.

Les écritures sont sérialisées par le groupe GitHub Actions `shadow-state`.
Une observation historique ne doit jamais être réécrite. PostgreSQL reste la
cible finale ; cette branche est reconstruisible par replay.
