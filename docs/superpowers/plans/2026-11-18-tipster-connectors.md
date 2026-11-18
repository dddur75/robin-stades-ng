# Connecteurs publics des 57 sources

**Objectif :** exécuter les lectures autorisées et montrer leurs résultats réels dans Robin local.
**Architecture :** profils individuels issus du registre, lecteurs RSS/Atom/HTML réutilisés, transport HTTPS public borné, journal local append-only. Aucun changement du collecteur épinglé J12. C0/root est le seul rédacteur de cette phase.
**Autorité :** demande explicite du propriétaire du 18 novembre pour développer et vérifier les 57 sources. Choix C0 : canari de trois sources puis qualification des 57, au plus quatre GET par source et 228 au total, sans compte, achat, API-Football, redirection automatique ni conservation de texte fournisseur. Mission E1 puis E2 seulement, expiration explicite. Les robots et les conditions actuelles précèdent le contenu. Une règle absente ou ambiguë ferme la collecte.

- [x] Profils et tests ciblés : couverture exacte des 57 IDs, formats, droits et attribution.
- [x] Exécution : réservations durables avant réseau, exclusion mutuelle, reprise sans dépassement, intégrité, DNS public et adresses épinglées, délais par hôte.
- [x] Lecture réelle : robots, conditions et contenu permis, métadonnées et faits structurés uniquement; aucun article n'est compté comme un pronostic humain vérifié.
- [x] Cockpit : état de chaque connecteur, reçus, publications, candidats à rapprocher et exécution explicite séparée de la consultation.
- [ ] Recette : erreurs et concurrence, canari réel puis qualification autorisée, relecture indépendante C1/C4 et C3/UX6/A3, preuve et CI de la PR133.

Les réglages préparatoires restent des propositions. Les profils exécutables épinglés ne changent jamais d'adresse parce qu'un utilisateur modifie un brouillon. Un nouveau plan est nécessaire pour adopter un réglage. La collecte fonctionne localement; un déploiement public ou un ordonnanceur récurrent serait une livraison distincte. Les journaux chiffrés et les métriques observées sont distingués des pronostics réellement attribués, rapprochés et vus avant match.
