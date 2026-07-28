# Rapport d’accessibilité

## Résultat

La V1 met en place les fondations WCAG 2.2 AA demandées : structure sémantique, contraste, navigation clavier, focus visible, alternatives textuelles aux graphiques, réduction des mouvements et libellés explicites. Ce rapport n’est pas une certification externe ; il documente les contrôles réalisés et les limites restantes.

## Contrôles réalisés

| Domaine | Preuve |
|---|---|
| Langue | `<html lang="fr-FR">` sur toutes les routes |
| Titres | un `h1` explicite par vue, progression de niveaux contrôlée |
| Repères | `header`, `nav`, `main`, `aside`, `footer` |
| Évitement | premier lien « Aller au contenu principal », cible focalisable |
| Clavier | test Playwright Tab → focus visible → Entrée → contenu principal |
| Focus | contour bleu de 3 px, décalé de 3 px, jamais supprimé globalement |
| Boutons | sélecteur avec `aria-pressed`, groupes nommés, fermeture du drawer nommée |
| Onglets | rôles `tab`, `tablist`/navigation et `tabpanel`, état sélectionné |
| Progression | `progressbar` avec nom et valeur textuelle |
| Statuts | symbole + texte + description ; jamais la couleur seule |
| Graphiques | résumé textuel et valeurs lisibles sans pointer |
| Glossaire | survol, focus et bouton tactile ; dialogue nommé |
| Animation | media query `prefers-reduced-motion` |
| Contraste forcé | règle `forced-colors` pour les contrôles essentiels |
| Zoom | structure tablette à 768 px utilisée comme proxy d’un desktop 1440 px à 200 % |

## Contraste

Les paires principales bleu nuit/blanc cassé et texte sombre/blanc dépassent la cible AA. Les textes secondaires restent réservés aux tailles supérieures au minimum. Orange, rouge, bleu, vert et violet ne portent jamais seuls le sens.

## Défauts détectés et corrigés

- Nom accessible perdu sur le bouton du glossaire mobile.
- Logo mobile nommé seulement « Robin ».
- Cible du lien d’évitement non focalisable après activation.
- Débordement de la frise Laboratoire à 390 px.

## Lecteur d’écran

Le snapshot d’accessibilité du navigateur confirme la lecture des noms de navigation, des boutons de vue, des statuts, des progressions, de la fiche à neuf onglets et des états vides. Les codes techniques restent absents de la Vue essentielle et sont rendus comme `code` en Expert.

## Limites et suivi

- Une revue humaine avec NVDA et VoiceOver reste recommandée avant une ouverture au grand public.
- Les graphiques futurs devront conserver une table ou un résumé, même si une bibliothèque est ajoutée.
- Les tableaux très larges restent un usage Expert : le scroll local ne remplace pas une sélection de colonnes réfléchie.
- Les contrastes devront être recalculés si les jetons de couleur changent.
