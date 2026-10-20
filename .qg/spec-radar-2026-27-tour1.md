# PR 124 — relecture de Claude, tour 1

Demande de David du 20/10/2026 : lire la relecture, corriger la CI sur la même
branche, ajouter l'EV disponible au relevé et pousser avec le SHA.

- CI : reproduire les échecs, corriger leur cause sans affaiblir les tests.
- EV_direct = prix FR × fair Pinnacle contemporain − 1. Triplet 1N2 complet
  au relevé le plus proche à ±15 min inclusives, antérieur en cas d'égalité ;
  observations et ingestions avant kickoff, ingestion au plus tard FR+15 min.
- Sans référence contemporaine : non calculable, jamais fair de clôture en secours.
- Même seuils >0, ≥2 %, ≥5 %, premiers franchissements uniques par sélection et
  seuil, book × bande de fair direct × horizon ; conserver les détails séparés.
- Dans chaque semaine et le cumul : comparaison directe/clôture, gains directs,
  confirmation par seuil : prix au premier franchissement direct encore EV>0
  contre le fair de clôture. Dénominateur de clôtures connues et absences explicites.
- Vérifier les empreintes des archives existantes ; produire un bilan réel si accessible.
- Garder tous les garde-fous papier : aucun fournisseur, achat, pari, Neon/R2,
  abonnement, scraping ou modification de collecte ; une seule PR, sans fusion.

## Cause CI vérifiée

15 échecs de Quality and domain tests sur 211822a : les nœuds RADAR-001/002
ont été placés en tête de decision_nodes au lieu d'être ajoutés en fin. Les
préfixes historiques ne correspondaient donc plus au ledger. Le job tests est
un agrégateur qui échoue par propagation de Quality. Déplacement du seul ajout
RADAR en fin de tableau, dans l'ordre du ledger ; aucun contrôle désactivé.

## Résumé de livraison

- Cause CI corrigée : ordre des nœuds, sans changement des tests ni du ledger historique.
- EV directe, confirmation par seuil et dénominateurs ajoutés au cumul et aux quatre semaines.
- 270/270 archives/JSON vérifiés ; 2 691 EV directes calculables, 450 prix FR manquants.
- 8 opportunités directes >0, 2 à ≥2 %, aucune à ≥5 % ; confirmation 6/8 et 2/2.
- Audit : 2 033 514 lignes normalisées ; aucun label boost explicite, non-étiquetés inconnus.
- 46 tests CLV/radar passent ; contrôle des triplets réels des premières opportunités effectué.
- Ruff, mypy strict du module direct, Bandit ; revue indépendante et CI distante à suivre.
- Zéro fournisseur/achat/abonnement/pari/Neon/R2 ; aucune fusion.
