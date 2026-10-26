# Dossier fidèle — conformité §04/05/19

Module local, sans collecte, publication, pari ni effet en production.
Les objets sont des dataclasses figées. La chaîne est `Source → Publication →
PublicationVersion → Contribution → MatchMarket → Result → Evaluation`.

Les quatre horodatages de version ont des sens distincts, sans obligation
d'avoir des valeurs différentes. Les dates annoncée et de modification peuvent
être inconnues (`None`); observation et disponibilité sont fournies explicitement.
Aucune date n'est créée à partir de l'heure courante. Une modification observée
ne peut devenir utilisable avant son observation. Une disponibilité égale ou
postérieure au coup d'envoi exclut l'évaluation pré-match; coup d'envoi inconnu,
identité manquante ou ambiguë : exclusion aussi.

Les cotes sont des `Decimal` explicites, jamais complétées l'une par l'autre.
Leur représentation JSON est une chaîne décimale exacte ou `null` (schéma T3).
L'évaluation choisit explicitement `cote_declaree` ou `cote_observee`.
Chaque contribution conserve auteur, publication et version, URL, langue,
match et certitude du rapprochement, liens de reprise, ligne et période.
Un extrait nécessaire de 500 caractères au plus est permis uniquement avec
une URL de preuve de permission ; empreinte et positions restent obligatoires.
Les payloads fournisseur complets sont interdits. Chaque cote conserve sa
provenance et son instant ; le bookmaker inconnu reste `None`.

Chaque instant est enregistré avec `utc`, `origin_timezone` (clé IANA ou nom
du décalage fixe) et `origin_offset_seconds`. Les fuseaux IANA requièrent une
base système ou `tzdata`, notamment sur Windows.

`pre_match_contributions` retient toutes les sélections de la dernière version
utilisable avant le coup d'envoi. Une correction chaîne `previous_version_id`
et conserve la première observation. Le scénario A conserve donc la version
de 18 h ; le scénario B reste rétrospectif.

`settle` applique les règles documentées/versionnées : `1N2`/`1X2` utilise le
score réglementaire, `qualification` le qualifié distinct, `total` et `handicap`
la ligne explicite (handicap du côté sélectionné). Les quarts de ligne divisent
la mise entre les demi-lignes adjacentes. `settle_combined` conserve les jambes
et multiplie leurs retours, y compris les demi-règlements. Le produit des cotes
explicites des jambes doit correspondre à la cote retenue du combiné.
Règle absente, période non prise en charge, qualifié inconnu, cote de jambe
manquante ou report sans remboursement documenté : `en_attente`.
Un résultat en attente peut être finalisé par ajout avec `previous_result_id`.
Une correction d'un résultat déjà réglé exige aussi `audit_evidence_sha256`.

`reprise_groups` ne joint que les reprises attestées. `origin_groups` expose
les origines non résolues, y compris les cycles ; la similarité reste un indice.
La provenance d'une publication Robin n'est jamais réécrite. Groupes de reprises
et nombre de matchs distincts sont comptés séparément.

`IdentityRevision` ajoute les affectations de comptes à une identité ; fusion
puis séparation se recalculent depuis les comptes d'origine. `Withdrawal`
conserve les contributions et leurs pertes, signale la couverture modifiée et
impose `Comparable suspendu`, même pour une publication sans résultat.
`visit_coverage` = visites planifiées réussies/planifiées ; ce n'est pas le rappel.

`rankings(..., odds_basis=...)` sépare les cotes déclarées/observées et les
catégories : ROI à mise unitaire, descriptif sans cote, Brier/log-loss pour les
probabilités explicites, exactitude/antériorité pour les faits. `calibration`
emploie uniquement les probabilités et résultats binaires explicites.
Une probabilité extrême fausse produit une log-loss infinie.

`Cohort` fige membres, fenêtres d'évaluation/réserve prospective, seuils et
empreinte des critères avant toute évaluation enregistrée. La fonction pure
`classification_state` reçoit les mesures de ces fenêtres et contrôle
Découverte → En observation → Comparable → Signal prospectif.
`rankings` reste En observation, ou suspendu après retrait ; aucune promotion
implicite, aucun ordonnanceur ni exécution de workload.

`AppendOnlyStore` accepte uniquement les types du module, vérifie les liens,
refuse les identifiants réutilisés et les mutations/suppressions. Chaque ligne
JSONL canonique contient le hash de la précédente. Le lecteur vérifie la chaîne,
les objets et leurs liens; une instance conserve aussi son dernier préfixe.
Au redémarrage, `expected_head` permet d'ancrer une tête précédemment conservée.
Un hash seul ne protège pas d'une réécriture complète par un tiers disposant
du fichier et de son ancre. Contrat : un seul rédacteur, aucun contrôleur concurrent.

Le schéma fermé `schemas/contribution.schema.json` décrit le contrat complet.
Les comparaisons entre champs (offsets, empreintes, dates, calculs) sont vérifiées
par les objets et le journal. Les anciens journaux incomplets sont refusés ;
aucune migration silencieuse de preuve. Tests : `tests/source_observatory/`.
Plan : `reports/source_observatory/PLAN-CONFORMITE.md`. Aucun commit.
