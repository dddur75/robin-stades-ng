# Internal Market Data Retention Policy V1

## Statut et portée

Identifiant : `INTERNAL_MARKET_DATA_RETENTION_POLICY_V1`.

Cette politique est une décision interne à risque non nul et borné : `NON_ZERO_BOUNDED_INTERNAL_DECISION`. Elle autorise uniquement la mécanique d'un `bounded research pilot`, sous autorisation live séparée. Elle ne prétend pas que The Odds API a accordé une autorisation contractuelle explicite de conservation et n'autorise pas une archive brute permanente ou pleine saison.

Elle remplace, pour ce seul pilote borné, le gate `RAW_PAYLOAD_RETENTION_WRITTEN_CONFIRMATION_REQUIRED`. Elle ne supprime aucun autre gate scientifique, budgétaire, de mapping, de settlement, de sécurité ou d'autorisation live.

## Contrat obligatoire

| Règle | Valeur |
|---|---|
| Finalité | internal analytics only |
| Revente | interdite |
| Redistribution | interdite |
| Endpoint public brut | interdit |
| Stockage brut | local non-synchronised |
| TTL brute | 30 jours exacts |
| Observations normalisées | conservées |
| SHA-256 brut | conservé |
| Données dérivées | conservées |
| Suppression | automatisée et obligatoire |
| Risque juridique | NON_ZERO_BOUNDED_INTERNAL_DECISION |
| Périmètre | bounded research pilot |
| Archive brute permanente / pleine saison | interdite |

Le contrat exécutable `InternalRetentionPolicy` est immuable et refuse les champs supplémentaires. Le store refuse de démarrer sans cette politique, sans une racine locale explicitement approuvée et identique à la racine demandée, dans Git ou dans un chemin dont un segment correspond à un service de synchronisation connu. La détection par nom est une défense complémentaire, pas une preuve universelle : avant tout live, l'autorité devra aussi fournir une vérification OS-backed des racines Cloud Files, lecteurs réseau et services de synchronisation installés.

## Cycle de vie

À la première observation, les octets sont hachés en SHA-256 avant parsing. Un reçu d'intake fixant l'échéance brute à `robin_first_observed_at + 30 jours` est durable avant l'écriture sous adresse de contenu. Les payloads dépassant la borne ne sont pas conservés bruts.

À l'échéance, `enforce_raw_ttl` :

1. vérifie l'intégrité SHA-256 avant suppression ;
2. conserve un brut encore référencé par au moins un reçu non expiré ;
3. sérialise le sweep avec toute capture concurrente au moyen d'un verrou fichier inter-processus, puis écrit et fsync une intention dans le `deletion-ledger.jsonl` hash-chaîné ;
4. supprime les seuls octets bruts arrivés à expiration, puis écrit le commit ;
5. conserve reçu, hash brut, observations normalisées, manifest et données dérivées.

Le mécanisme est couvert par un test déterministe. Avant toute activation live, son invocation périodique devra être liée à l'orchestration autorisée; l'absence de cette liaison est une condition d'arrêt et non une permission de conserver plus longtemps.

## Interprétation des conditions publiques

Les [conditions publiques officielles](https://the-odds-api.com/terms-and-conditions.html), relues le 15 août 2026, encouragent les sites, applications, dashboards et outils analytiques, y compris commerciaux, tant que les données ne sont pas revendues, repackagées ou redistribuées comme produit de données autonome. Elles exigent aussi que la clé reste privée. Elles ne donnent pas de durée publique de conservation brute.

L'interprétation interne est donc limitée : l'usage analytique interne, sans redistribution et avec suppression brute à 30 jours, est compatible avec la finalité publique décrite, mais le silence sur la durée conserve un risque résiduel. La politique borne ce risque; elle ne transforme pas ce silence en droit explicite.

Le seul domaine institutionnel retenu est `the-odds-api.com`, conformément à l'[avertissement officiel contre le domaine sans tirets](https://the-odds-api.com/impersonation-warning.html). Le host technique futur est limité à `api.the-odds-api.com`, documenté dans le [guide V4 officiel](https://the-odds-api.com/liveapi/guides/v4/).

## Conditions d'arrêt

Le pilote doit rester ou redevenir inactif si l'une des conditions suivantes survient :

- la TTL de 30 jours ou la suppression automatisée ne peut pas être garantie ;
- le stockage est dans Git, synchronisé, partagé publiquement ou accessible par un endpoint brut ;
- une clé, URL authentifiée ou valeur sensible apparaît dans un log, reçu, fingerprint, manifest, exception ou fichier ;
- une revente, redistribution ou republication brute est envisagée ;
- le périmètre dépasse le pilote de recherche borné ;
- une archive brute permanente ou pleine saison est demandée ;
- les conditions publiques changent ou deviennent incompatibles ;
- une ambiguïté juridique nouvelle ne peut pas être bornée sans autorité externe.

Aucun contact externe n'a été effectué dans cette mission. Toute demande de clarification fournisseur relèverait d'une mission et d'une autorisation séparées.

## Verdict

```text
INTERNAL_MARKET_DATA_RETENTION_POLICY_V1_RECORDED
LEGAL_RISK_NON_ZERO_BOUNDED_INTERNAL_DECISION
BOUNDED_RESEARCH_PILOT_ONLY
FULL_SEASON_PERMANENT_RAW_ARCHIVE_NOT_AUTHORIZED
```
