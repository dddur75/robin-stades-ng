# Généralisation des features joueurs

Statut : `PLAYER_GENERALIZATION_INCONCLUSIVE`.

Les cinq ligues disposent d’effectifs historiques, mais pas encore de
statistiques joueurs par match ni de compositions couvrant au moins 90 % et
85 % des fixtures. Aucun effectif n’est transformé en statistique de match,
aucune valeur manquante n’est remplacée par zéro et aucune blessure
rétrospective n’entre dans les features.

Les contrôles permutation joueurs, features constantes et lineups aléatoires
sont enregistrés comme non applicables tant que leurs gates sont bloqués. Le
contrôle de cible permutée passe sur les trois datasets équipe prêts et la
feature future synthétique est bloquée par la garde anti-fuite.
