# Jalon 12 — rapport de l’Observatoire prospectif

## Synthèse technique

Le contrat, l’architecture R2-first, les fenêtres, les budgets et la surface
Robin Live sont préparés pour mesurer les captures prospectives sans conclusion
sportive prématurée. Le snapshot versionné initial est
`WAITING_FOR_FIRST_DUE_WINDOW` et sa provenance est
`NO_PROSPECTIVE_CAPTURE_YET` : zéro fixture ou capture n’est inventé.
La provenance des politiques est
`configs/prospective_observatory_v1.json`.

Ce document est un rapport évolutif. Les compteurs opérationnels ne deviennent
des preuves qu’après un pilote réel sur des fenêtres effectivement dues et un
replay R2 vert.

## État observable initial

| Mesure | Valeur initiale | Interprétation |
|---|---:|---|
| Fixtures prospectives publiées | 0 | registre réel non encore injecté dans le snapshot versionné |
| Fenêtres dues | 0 | aucun appel à forcer |
| Captures revendiquées | 0 | aucune donnée démo |
| Appels API-Football | 0 | plafond pilote 5 000 |
| Crédits The Odds API | 0 | plafond pilote 250, admission planifiée 248 |
| Décisions de pari | 0 | interdites dans le jalon |
| Payloads bruts Git | 0 | objectif contractuel |

Les réserves protégées sont 5 000 appels API-Football, 4 000 crédits The Odds
API et 80 crédits dédiés aux fenêtres proches du kickoff. Les valeurs runtime
doivent porter leur provenance avant tout appel.

## Périmètre, données et définitions

Le pilote P0 couvre la Ligue 1 sur trente jours et au plus trois journées. Les
quatre autres grandes ligues restent P1. Les neuf familles sont suivies au grain
fixture × fournisseur × famille × fenêtre.

Une capture est temporellement admissible uniquement si :

```text
response_received_at < cutoff_at < kickoff_at
```

`CAPTURED_EMPTY` compte comme observation réelle. `MISSED_WINDOW`,
`TEMPORALITY_FAILED` et `IDENTITY_FAILED` restent visibles et ne sont jamais
imputés.

## Méthode

Le scheduler horaire sélectionne les fenêtres préenregistrées dues, puis vérifie
budget, réserve et circuit breaker. Les octets reçus sont hashés et stockés
append-only dans R2. PostgreSQL conserve les index et projections, jamais les
corps volumineux. Le replay reconstruit une base jetable sans fournisseur.

Robin Live lit un rapport compact nettoyé et ne contacte ni R2, ni Neon, ni un
fournisseur depuis le navigateur.

## Gates et hypothèses

Les gates joueur, blessure, lineup, formation et marché commencent à
`WAITING_FOR_OBSERVATIONS`. H11-001 à H11-008 gardent leurs seuils gelés de 80
à 120 occurrences selon le protocole. Zéro observation implique zéro test,
pas un résultat négatif.

Les cinq cartes publiques — buteur en forme contre deux centraux absents,
4-3-3 contre 4-4-2, gardien titulaire absent, continuité du onze et pied fort —
affichent données requises, accumulation, statut et première date possible.
Elles n’affichent aucune conclusion.

## Limites et robustesse

- aucun pilote réel ne peut être déclaré depuis le snapshot initial ;
- l’absence de fenêtre due ne teste pas les capacités lineup/injury/odds ;
- un workflow vert sans progression de données ne suffit pas ;
- la couverture agrégée ne remplace pas un gate au grain fixture ;
- l’historique post-match ne prouve pas la disponibilité prospective ;
- les dates possibles d’analyse dépendent des fixtures et captures réelles.

## Étapes suivantes

1. appliquer `0009_jalon12_observatory` ;
2. exécuter le registre Ligue 1 ;
3. publier le coût et les fenêtres dues ;
4. capturer seulement ces fenêtres ;
5. vérifier R2 et PostgreSQL ;
6. rejouer sur une base jetable ;
7. actualiser ce rapport et Robin Live ;
8. conserver la PR Jalon 12 non fusionnée.

## Questions ouvertes

- quelles familles le fournisseur expose-t-il réellement à chaque fenêtre ?
- combien de journées faut-il pour atteindre deux fenêtres critiques par
  famille ?
- les réserves runtime permettent-elles P1 sans menacer le live existant ?
- à quelle date chaque hypothèse atteint-elle son minimum préenregistré ?

Ces questions sont des objectifs de mesure, pas des résultats.
