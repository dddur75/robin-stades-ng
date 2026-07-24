# Résolution des identités

Statut : `VERIFIED` pour le registre et les contraintes du jalon 1

## Principe

Un identifiant interne est un UUID créé par Robin. Il est indépendant des noms et
des identifiants fournisseurs. Un nom observé est un attribut, jamais une preuve
d'identité.

Types opérationnels :

- compétition ;
- saison ;
- équipe ;
- joueur ;
- arbitre ;
- match ;
- bookmaker ;
- marché ;
- sélection ;
- snapshot de cote ;
- prédiction ;
- stratégie ;
- version de modèle.

## Correspondances fournisseurs

Chaque liaison contient :

```text
internal_entity_id
provider_name
provider_entity_id
valid_from
valid_to
mapping_status
mapping_confidence
mapping_method
review_status
```

La résolution automatique est autorisée uniquement sur une clé fournisseur
explicite déjà liée. Deux fournisseurs utilisant le même nom créent deux entités
distinctes tant qu'une liaison explicite n'est pas validée.

## Changements et homonymes

- changement de nom : nouvelle observation du nom, même UUID si la clé source
  reste liée ;
- fournisseur changeant d'identifiant : nouvelle correspondance versionnée ;
- homonymes : UUID différents ;
- équipes masculine, féminine ou réserve : entités différentes avec attributs de
  catégorie ;
- transfert joueur : l'identité du joueur reste stable, la relation d'effectif est
  versionnée ;
- renommage/fusion/disparition : aucune suppression ; statut et périodes de
  validité sont conservés ;
- deux noms proches : jamais fusionnés automatiquement.

## Conflits

Plusieurs mappings actifs pour la même clé fournisseur constituent une erreur
bloquante. La similarité textuelle peut produire une proposition `PENDING`, jamais
une correspondance `CONFIRMED`.

## Stabilité

Le service transactionnel garantit qu'un second import de la même clé fournisseur
retourne le même UUID et ne crée pas de doublon. Une liaison inter-fournisseur est
une action explicite et auditée.
