# 027 — phase 3 — capture sans migration

Demande de David, 2026-10-17 ; suite de la spec qg#72 et de robin-stades-ng#109.
Base : `main@046dd0e420eff61469f309cf9e8ec12ba7ebfe28`.
Rédacteur unique nommé pour cette phase : Codex (C0), sans sous-agent.

## Objectif et contraintes

- Préparer la capture 2026-27 des cinq ligues sans migration de production.
- Choix autorisé : état durable dans R2 uniquement ; aucune connexion Neon.
- Conserver 60 appels de données/jour UTC, réserve fournisseur de 5 000,
  fenêtres avant kickoff, compteurs et cache `/status` de la phase 2.
- Ne pas activer le workflow 321915843, lancer de collecte, ni fusionner.
- Livrer une PR vers `main`, tests à jour ; relecture indépendante requise.

## Preuves et recette

Le run 39063276656 échoue au garde exigeant `0015_data_torrent_opportunity`,
avant estimation et capture. Son journal ne révèle pas la révision actuelle.
Aucun accès Neon n'est configuré dans cette session : révision non vérifiée,
`0013` n'est pas affirmée. Le choix R2 seul ne dépend d'aucune révision SQL.
Les reçus, budgets, marqueurs de calendrier et tentatives incertaines restent
dans les espaces R2 existants ; l'état mémoire se reconstruit à chaque run.
L'index PostgreSQL ne reçoit donc plus les nouvelles captures de ce workflow.
Une décision séparée de David serait nécessaire pour changer ce choix.

Recette hors ligne : estimation sans appel, capture sans URL SQL et avec URL
SQL inutilisable, reprise dans un nouvel état mémoire, reçus et quota conservés,
aucun doublon fournisseur ; régressions 60/61 et `/status` conservées.
Retour arrière : rétablir le commit de phase 3, workflow laissé désactivé ;
conserver les objets R2 et leurs réservations, sans downgrade SQL.

## Résumé de fin

- Fait : chemin R2 seul, secrets SQL retirés du workflow, tests de reprise.
- Recette : 536 tests ciblés verts ; Ruff, Bandit, mypy et contrôles de secrets.
- Limite locale : 12 contrôles historiques bloqués par l'historique Git absent,
  détaillés dans `reports/evidence/mission027-phase3-public-receipt.json`.
- Reste : relecture indépendante, CI et intégration ; activation par David.
- Reste : reçu réel d'au moins dix matchs après activation autorisée.
- Risques : données nouvelles absentes de l'index Neon ; révision non vérifiée.
- Aucun appel fournisseur/R2/Neon, aucune migration ni activation par la session.
