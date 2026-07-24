# Cockpit Shadow V1

Statut produit : `PARTIAL`  
Statut shadow : `SHADOW_INFRASTRUCTURE_READY`  
Paris réels : `PRODUCTION_LOCKED`

## Questions couvertes

| Vue | Question opérationnelle |
|---|---|
| Command Center | La chaîne est-elle exploitable maintenant ? |
| Match Center | Quelles données et probabilités existent pour ce match ? |
| Odds Monitor | Quelles cotes authentiques ont été observées, quand et où ? |
| Shadow Bets | Pourquoi une opportunité a-t-elle été retenue ou rejetée ? |
| Data Quality | Quel contrôle doit bloquer ou dégrader la décision ? |
| Strategy Lab | Une stratégie résiste-t-elle réellement hors échantillon ? |

## Contrat de provenance

- `DEMO DATA` : fixture et décision synthétiques, uniquement pour valider l'UI ;
- `LEGACY SOURCE` : données historiques sans preuve prospective complète ;
- `LIVE SOURCE` : réservé aux payloads réellement reçus d'un fournisseur.

Les origines historiques et prospectives ne sont jamais agrégées dans une même
performance sans distinction. L'absence de snapshot réel produit un état vide
explicite.

## Données

`scripts/build_cockpit_snapshot.py` produit
`cockpit/app/cockpit-data.json` depuis les artefacts versionnés. Le dashboard
n'appelle aucune IA par match et effectue uniquement des filtres locaux.

## Validation

Le smoke test compile le site, vérifie le rendu serveur, les six vues, les badges,
le verrou `PRODUCTION_LOCKED`, l'image sociale et l'absence du squelette starter.
La navigation a également été testée dans le navigateur local sans erreur console.

## Ouverture

Déploiement privé :
`https://robin-stades-shadow-cockpit.dddur.chatgpt.site`

Localement :

```powershell
cd cockpit
pnpm dev
```

Puis ouvrir `http://localhost:3000`.
