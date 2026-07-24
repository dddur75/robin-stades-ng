# Immutabilité des données brutes

Statut : `VERIFIED` pour le backend local du jalon 1

## Observation et payload

Chaque appel fournisseur produit une observation distincte contenant :

```text
provider
endpoint
request_parameters
requested_at
received_at
http_status
payload_hash
schema_version
ingestion_run_id
raw_payload_location
```

Le payload est adressé par SHA-256. Deux réponses identiques créent deux
observations, mais référencent le même objet physique. Une réponse différente crée
un nouvel objet.

## Règles d'écriture

- création exclusive des fichiers avec échec si le chemin existe ;
- un objet existant est relu et comparé avant réutilisation ;
- aucune API de mise à jour ou suppression ;
- métadonnée d'observation créée en mode exclusif ;
- contrôle du hash à chaque relecture ;
- paramètres sensibles remplacés par `[REDACTED]`, y compris dans les structures
  imbriquées.

## Reproductibilité

Une transformation normalisée conserve l'identifiant de l'observation brute et sa
version de schéma. Elle peut donc être rejouée sans nouvel appel réseau.

Le backend `LocalPayloadBackend` respecte l'interface `PayloadBackend`. Un futur
backend S3 pourra appliquer les mêmes règles avec écriture conditionnelle,
versionnement objet et politiques de rétention.

## Organisation locale

```text
data/raw/
├── payloads/<préfixe>/<sha256>.bin
└── observations/YYYY/MM/DD/<uuid>.json
```

Ces objets ne sont pas nécessaires aux tests distants : les tests utilisent un
répertoire temporaire et un fournisseur mock.
