# Catalogue complet du classeur — plan d’intégration

> C0 est l’unique rédacteur de cette phase. C1/C2/C4 relisent sans modifier.

**Goal:** exposer toutes les références du classeur fourni dans Robin et enrichir sa copie avec les états de collecte réellement prouvés.

**Architecture:** réutiliser l’extraction locale des neuf onglets, index privé immuable séparé du registre317 ; endpoint local paginé et recherche côté serveur. Conserver les identifiants, reçus et évaluations des317. Les fiches supplémentaires sont documentaires tant qu’une preuve individuelle et une campagne applicable ne sont pas établies.

**Tech Stack:** Python, Vite/Vinext, React, runtime Spreadsheets fourni.

## Contraintes

- Phase locale0GET éditeur ; aucun replay de corpus ni nouveau census réseau.
- Classeur source inchangé, copie enrichie dans outputs ; pas de données détaillées du classeur dans Git.
- Aucune fusion de personnes par pseudo. Types et provenance onglet/ligne conservés ; compétition inconnue reste inconnue.
- Aucun changement des campagnes ou30pins existants. Qualification réseau additionnelle sous manifeste distinct relu C0/C1/C4.
- Les métriques réelles auront un claim et des empreintes ; conserver toutes les décisions antérieures append-only.

## Étapes

- [x] Vérifier les empreintes et réconcilier indépendamment les neuf onglets et les18003adresses des deux inventaires.
- [x] Construire et tester un index local immuable, liens sûrs et filtre/recherche/pagination/lookup bornés, sans attribuer de preuve à une nouvelle fiche.
- [x] Ajouter une page catalogue complet reliée à l’admin et au catalogue317 ; préserver le repli317 si index absent et les requêtes concurrentes indépendantes.
- [x] Enrichir une copie du classeur, préserver les onglets et valeurs historiques ; fournir états courants et accès manquants avec provenance.
- [x] Tester synthétiquement le domaine et les parcours localdesktop/mobile ; relecture C1/C2/C4, preuve locale et bilan réel.
- [x] Pour toute nouvelle source collectable : plan borné distinct, droits/robots avant contenu, preuve personnelle avant match, aucune activation déduite de l’import.

## Points de revue

- Adresses et types de référence ne sont pas un nombre de personnes.
- ÉtiquettesA et dates historiques ne sont pas des pronostics actuels admissibles.
- Recherche et pagination ne doivent pas télécharger18k fiches toutes15secondes.
- L’absence du compagnon ne doit pas couper les fiches317.
- Réponses concurrentes avec filtres différents ne doivent pas partager le résultat d’une autre requête.
