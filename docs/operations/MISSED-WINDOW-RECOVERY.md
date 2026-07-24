# Récupération d’une fenêtre manquée

## États

Une fenêtre devenue due passe à `DUE`. Sans collecte, elle devient
`MISSED_RECOVERABLE` pendant 120 minutes après sa limite. Une collecte réussie
pendant cette marge devient `COLLECTED_LATE`. Après la marge, elle devient
`MISSED_FINAL`.

## Procédure automatique

1. restaurer le dernier registre durable ;
2. recalculer les états à partir du kickoff UTC et de l’heure courante ;
3. prioriser H-0:10, H-0:30 et H-1 avant les fenêtres lointaines ;
4. respecter réserve et plafond de quota ;
5. relancer seulement les fenêtres récupérables ;
6. écrire avec la même identité métier ;
7. vérifier l’acquittement durable avant de compter la fenêtre.

Le test adversarial Jalon 4 prouve la transition
`MISSED_RECOVERABLE → COLLECTED_LATE`. Il s’agit de `TEST EVIDENCE`, pas d’une
fenêtre live collectée. Un diagnostic manuel ne modifie jamais la heatmap.

## Incidents

`PROVIDER_FAILED` déclenche une reprise bornée. `NO_MARKET_AVAILABLE` est une
observation valide. `SKIPPED_QUOTA` protège la réserve. Aucun de ces états ne doit
être remplacé par une donnée synthétique.
