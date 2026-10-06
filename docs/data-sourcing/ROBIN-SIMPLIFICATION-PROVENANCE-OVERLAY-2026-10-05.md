# Addendum de provenance de la simplification Robin

Cet addendum couvre uniquement le contrat de provenance des futures acquisitions.
Il ne réinitialise ni l’autorité, ni les budgets, ni l’expiration du laboratoire
autonome. Il n’autorise aucun appel fournisseur, accès R2 ou déclenchement de
workflow.

## Frontière factuelle

Les enveloppes historiques `robin-autonomous-raw-envelope-v1` ne portaient ni
identifiant de route fournisseur, ni période de règlement attestée, ni bornes de
début et de fin d’acquisition. Ces quatre champs restent donc `null` à la lecture.
Ils ne sont jamais reconstruits à partir de constantes, et les objets historiques
ne sont pas réécrits.

Les futures enveloppes `robin-autonomous-raw-envelope-v2` enregistrent :

- la route `THE_ODDS_API_V4` effectivement utilisée par le collecteur ;
- `PROVIDER_DEFAULT_UNSPECIFIED` pour la période, car le contrat V4 des cotes
  identifie les marchés `h2h` et `totals` sans attester une période de règlement
  football plus précise ;
- les instants UTC observés immédiatement avant et après la requête de la branche.

Une comparaison ancienne/nouvelle, ou toute comparaison dont une seule moitié de
la provenance est renseignée, est exclue avec un motif explicite. Les acquisitions
v1 entre elles restent comparables sur leur identité historique, avec provenance
affichée comme inconnue. Cette compatibilité ne change aucun résultat scientifique.

Référence fournisseur : documentation V4 officielle de The Odds API,
`https://the-odds-api.com/liveapi/guides/v4/`, endpoint odds et paramètres
`sport`, `regions`, `markets`, `dateFormat` et `oddsFormat`.
