# Audit de l’antériorité tennis

Date : 2026-07-27
Portée : lecture statique bornée, hors dépôt
Part maximale du Jalon 10 : environ 10 %

## Empreinte de l’archive

- SHA-256 :
  `9e48a1b643680062d1871b4b5ce14f6097d12bf5a60f08dea13ce70c25564c47` ;
- taille : 550 586 octets ;
- inventaire statique : 29 entrées, dont 28 fichiers ;
- extraction : répertoire temporaire hors Git, supprimé après l’audit ;
- copie dans Robin : aucune.

## Qualification

L’archive ATP jointe est un retour d’expérience, pas un cahier des charges
football ni une preuve scientifique. Le résultat déclaré sur quatorze jours
est une observation propriétaire non indépendante, non suffisante pour conclure
à une stratégie durable.

L’inventaire statique montre des datasets annuels ATP et des composants de
découverte, application de règles, filtrage contextuel, confiance, bankroll et
automatisation. Aucun fichier de l’archive ni aucune extraction n’est ajouté au
dépôt Robin.

## Sécurité

Signal : `LEGACY_HARDCODED_SECRET_DETECTED`

La valeur n’a pas été affichée, testée, utilisée, copiée ni commitée. L’archive
n’est pas une entrée d’exécution de Robin. Toute analyse est cantonnée à un
emplacement temporaire hors versionnement.

## Idées fonctionnelles retenues

- séparer découverte, filtrage, décision et suivi de bankroll ;
- produire des règles lisibles et des raisons de rejet ;
- automatiser un replay déterministe ;
- exposer un score de confiance comme explication, jamais comme probabilité
  calibrée sans preuve ;
- publier un historique complet, y compris les pertes et `NO BET`.

## Défauts méthodologiques à ne pas importer

- orientation `winner_*`/`loser_*`, impossible avant l’événement ;
- taux de réussite parfait construit à partir du vainqueur/perdant connu ;
- ROI et cotes issus de simulations ou d’aléas, pas de prix bookmaker observés ;
- exploration opportuniste sans dénominateur complet des hypothèses ;
- risque de sélection du meilleur résultat sur une seule période ;
- absence possible de correction des tests multiples ;
- absence de walk-forward, de FDR et de protocole point-in-time ;
- incohérence de reproductibilité : 8 979 lignes CSV observées pour
  27 672 lignes annoncées ;
- confusion entre confiance heuristique, probabilité et edge ;
- optimisation de mise avant preuve de robustesse ;
- dépendance à des conventions tennis non transférables au football ;
- secret codé en dur.

## Tests anti-régression dérivés

Robin rejette explicitement :

- toute feature winner/loser ;
- le score ou les statistiques du match cible ;
- les labels mélangés qui semblent encore rentables ;
- les performances anormalement parfaites ;
- une règle non reproductible avant le cutoff ;
- une règle sans support, sans FDR ou concentrée sur une période ;
- tout secret dans le code, les données, les logs ou les exports.

## Décision d’architecture

Le code tennis n’est pas la base de Robin. Aucune règle, aucun ROI et aucun
dataset ATP n’est importé dans les registres football. Seuls des principes
généraux et des tests défensifs sont retenus.
