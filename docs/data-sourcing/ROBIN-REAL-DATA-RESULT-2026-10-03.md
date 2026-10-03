# Mandat propriétaire — résultat données réelles Robin

Reçu le 2026-10-03. Ce mandat succède aux restrictions opérationnelles des
missions `ROBIN_REPRISE_COLLECTE_20261002` et continuations, sans réécrire leur
historique.

> Reprends Robin avec une mission de résultat : faire circuler les données réelles jusqu’au tableau utilisable, réparer les défauts rencontrés, puis simplifier ce qui gêne inutilement le fonctionnement.
>
> Point de départ : main `150c14f76c5f51f0efa6211f4742ea2291a9234c`, PR #82 fusionnée, pilote `37118924677` terminé avec une tentative et zéro capture. Vérifie l’état courant sans refaire les validations inchangées. C0 reste l’unique writer Git.
>
> AUTORITÉ
>
> J’autorise les corrections nécessaires dans le code runtime, les tests, les dépendances, la configuration, les workflows et les procédures techniques directement concernées, ainsi que PR, CI, fusion normale et exécution réelle.
>
> Ce mandat remplace, pour cette mission, les anciennes restrictions opérationnelles « test-only », « un seul dispatch », « aucune nouvelle tentative » et leurs anciennes échéances. Matérialise cette nouvelle autorisation dans les contrôles concernés sans réécrire l’historique.
>
> DNS, utilisation des secrets existants, diagnostics réseau, lectures de quota, captures et stockage nécessaires sont autorisés dans l’enveloppe ci-dessous. Ne reviens pas demander une autorisation pour chaque réparation.
>
> PREMIER DÉFAUT À TRAITER
>
> Une reproduction hors réseau utilisant les classes actuelles `_DeadlineSocketRaw`, `_DeadlineSocketAdapter` et le vrai `http.client` révèle ceci : avec HTTP 200, `Connection: close` et un corps de 20 000 octets, la socket est fermée après les en-têtes ; la lecture échoue avec errno 9 après environ 8 Ko.
>
> Reproduis et corrige la durée de vie de cette socket, en préservant TLS, les délais et la fermeture finale. Ce défaut est confirmé localement ; son attribution au pilote passé reste une hypothèse.
>
> Conserve aussi un diagnostic expurgé exploitable : étape, code stable, classe d’exception, errno et statut HTTP lorsqu’il existe. Aucun secret ni URL contenant une clé dans les traces.
>
> RÉSULTAT ATTENDU
>
> Obtiens une première capture réelle, vérifie sa conservation et sa relecture, puis poursuis automatiquement.
>
> Rétablis la chaîne existante : fournisseur → stockage durable → normalisation/replay → tableau ou cockpit. Étends aux cinq ligues et aux marchés H2H/totals déjà pris en charge, sans ajouter de nouveau fournisseur.
>
> Démontre trois cycles programmés distincts sans intervention humaine. Présente les données reçues, leurs horodatages, leur couverture et leurs limites. Une branche indisponible ne doit pas arrêter les autres ; elle reste explicitement incomplète.
>
> Une fois le flux fonctionnel, supprime les rustines et contrôles techniques redondants démontrés inutiles sur ce parcours. Préserve les données, l’historique des échecs et les garanties scientifiques.
>
> MÉTHODE
>
> Diagnostiquer → réparer → vérifier le comportement concerné → poursuivre.
>
> Tests ciblés pendant les corrections, contrôles obligatoires avant fusion et une revue indépendante consolidée. Ne reconstruis pas tous les rapports après chaque petite modification. Ne crée pas un nouveau système de gouvernance pour réaliser cette mission.
>
> BUDGET GLOBAL
>
> Maximum cumulatif depuis le premier pilote : 40 requêtes HTTP fournisseur et 60 crédits, uniquement sur le quota existant. Les requêtes de diagnostic comptent aussi dans les 40.
>
> Réserve conservativement quatre crédits pour l’ancien échec tant que sa consommation reste inconnue. Vérifie le quota actuel sans prétendre que ce compteur reconstitue à lui seul la consommation passée. Comptabilise chaque nouvelle tentative avant émission.
>
> Horizon maximal : 72 heures à compter de cette autorisation, dont huit heures de travail actif. Arrête dès le résultat atteint. Aucun achat, rechargement ou changement d’abonnement. Aucun fonctionnement au-delà de cette enveloppe.
>
> Ne reviens avant livraison que pour un accès réellement manquant, un plafond atteint, une opération destructive nécessaire ou une décision produit/scientifique indispensable. Un nouveau bug réparable dans ce périmètre ne justifie pas un arrêt.
>
> Aucun pari, aucune promotion scientifique, aucun backfill ni faux résultat. Termine par les liens permettant de consulter les données réelles, le bilan des cycles et la consommation.

