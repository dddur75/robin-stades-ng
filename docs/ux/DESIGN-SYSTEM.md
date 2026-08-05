# Design system Robin

## Intention

Premium et sportif, mais calme. La surface évoque un observatoire et un carnet de terrain, pas un site de pari. Les microinteractions accompagnent la progression des données ; elles ne récompensent jamais une mise.

## Couleurs

| Jeton | Usage |
|---|---|
| Nuit 950 `#061722` | fond de structure profond |
| Nuit 900 `#082231` | rail, parcours et panneaux sombres |
| Nuit 800 `#123648` | structure intermédiaire |
| Encre `#102a36` | texte principal |
| Blanc cassé `#f7f5ef` | fond humain, contraste doux |
| Vert Robin `#16976a` | vérification, progression, identité |
| Bleu information `#2878cb` | collecte, explication |
| Orange attention `#cc7627` | données partielles ou attendues |
| Rouge erreur `#bc4d4b` | incident ou donnée invalide |
| Violet recherche `#7556b5` | hypothèses et exploration |

Les valeurs autoritatives sont les variables `:root` de `cockpit/app/globals.css`. Ce tableau est leur documentation lisible et doit être mis à jour dans le même lot que tout changement de jeton.

La couleur est toujours doublée par un libellé, une icône ou un motif. Le vert ne signifie pas « gain ».

## Typographie et rythme

- Titres éditoriaux : Georgia, pour une voix de publication.
- Interface et données : Geist, avec fallback système.
- Valeurs techniques : monospace seulement lorsque nécessaire.
- Corps minimal lisible ; interligne augmenté sur mobile.
- Grille de 8 px, rayons de 12 à 22 px, ombres sobres.

## Composants livrés

- rail et barre mobile de navigation ;
- sélecteur Vue essentielle / Vue expert ;
- en-tête de page et breadcrumb ;
- carte de métrique, match, hypothèse et capture ;
- badge de statut et de provenance ;
- jauge de couverture et barre de progression ;
- frise de capture et chronologie match ;
- matrice de couverture desktop et version verticale mobile ;
- courbe de bankroll accessible, résumé textuel et tableau de valeurs ;
- tableau riche : recherche, tri, colonnes masquables et CSV ;
- panneau explicatif, alerte et état vide ;
- onglets de fiche match ;
- drawer du glossaire ;
- terme de glossaire accessible au survol, au focus et au toucher ;
- accordéons Expert ;
- cartes de garanties.
- Desk de couverture P0 : double état définition/preuve, parcours conditionnel, trois taux indépendants, niveaux E0–E4, gates, table focalisable et couche de confiance.

## États

| État | Traitement |
|---|---|
| vérifié | symbole ✓, libellé et vert Robin |
| à venir | cercle, texte « À venir », ton neutre |
| partiel | demi-cercle, orange, explication |
| vide | symbole d’ensemble vide et cause |
| bloqué | libellé de prudence, action éventuelle |
| trop tard | rouge, heure limite expliquée |
| erreur | alerte, détail Expert |

## Interactions

- Hover discret, jamais indispensable.
- Focus visible de 3 px et décalage de 3 px.
- Touches de 42–44 px minimum pour les actions récurrentes.
- Drawer fermé par bouton nommé ; pas d’action implicite.
- Vue mémorisée localement ; aucune donnée scientifique recalculée.
- Animation désactivée par `prefers-reduced-motion: reduce`.

## Graphiques

Un graphique doit répondre à une question et fournir :

- titre et unité ;
- légende française ;
- valeur ou tableau accessible au clavier ;
- résumé textuel ;
- état vide ;
- comportement 390 px.

La V1 utilise du CSS et du HTML sémantique plutôt qu’une dépendance graphique lourde. La bankroll plate montre honnêtement l’absence de décisions.

## Image sociale

`cockpit/public/og.png` est une création originale Robin : terrain abstrait bleu nuit, trajectoires de données, accent vert, titre français et garantie « Aucun pari réel ». Elle n’utilise ni casino, ni billet, ni trophée financier.
