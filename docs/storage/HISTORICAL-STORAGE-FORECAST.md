# Prévision du stockage historique

Mesure avant compactage Jalon 5.1 : 3 162 fichiers locaux, 21 653 923 octets,
1 545 payloads gzip et 50 Parquet. Le registre Git migré contient 3 180
fichiers et 16 184 894 octets.

La projection observée à 63 638 appels est de 139 827 339 octets. Sans
compactage, environ 145 195 fichiers seraient produits ; les bundles par
run/compétition/saison/endpoint ramènent la projection à environ 483 objets
Git. Le bundle de validation réunit 3 096 fichiers dans une archive de
2 894 012 octets.

Chaque bundle contient un index, les hashes individuels, un hash global, une
version de schéma et une archive gzip. Un fichier reste rejouable
individuellement. La restauration développe les entrées uniquement dans
l’espace de travail.

Seuil d’alerte : 750 MB. Seuil de pause : 900 MB. À 900 MB, le checkpoint est
conservé et le backfill s’arrête ; une recommandation de stockage objet est
préparée sans souscription automatique.
