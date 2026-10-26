# Dossier fidèle — conformité §04/05/19

Module local, sans collecte, publication, pari ni effet en production.
Les objets sont des dataclasses figées. La chaîne est `Source → Publication →
PublicationVersion → Contribution → MatchMarket → Result → Evaluation`.

Les quatre horodatages de version ont des sens distincts, sans obligation
d'avoir des valeurs différentes. La date annoncée peut être inconnue (`None`);
une correction exige une date de modification observée et une disponibilité
strictement croissante. Observation et disponibilité sont fournies explicitement.
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
La limite est globale : cinq emplacements au plus, dont un seul avec texte,
sans chevauchement. Découper un article ne permet pas de contourner la limite.
Les payloads fournisseur complets sont interdits. Chaque cote conserve sa
provenance et son instant ; le bookmaker inconnu reste `None`.

Chaque instant est enregistré avec `utc`, `origin_timezone` (clé IANA ou nom
du décalage fixe) et `origin_offset_seconds`. Les fuseaux IANA requièrent une
base système ou `tzdata`, notamment sur Windows.

Chaque contribution fournit son propre `observed_at`, sans valeur imputée.
Sa disponibilité tient compte de cet instant et de celui de la version.
Le journal refuse l'antidatage derrière les observations et résultats déjà inscrits.
`pre_match_contributions` retient la dernière sélection utilisable par emplacement
avant le coup d'envoi. Une omission conserve la sélection antérieure et suspend
la comparabilité. Une correction chaîne `previous_version_id` et conserve la
première observation. Une sélection ajoutée après match reste rétrospective.
Un second `MatchMarket` pour la même contribution est refusé : aucun alias
ne permet de contourner l'audit des corrections de résultat.

`settle` applique les règles documentées/versionnées : `1N2`/`1X2` utilise le
score réglementaire, `qualification` le qualifié distinct, `total` et `handicap`
la ligne explicite (handicap du côté sélectionné). Les quarts de ligne divisent
la mise entre les demi-lignes adjacentes. `settle_combined` conserve les jambes
et multiplie leurs retours, y compris les demi-règlements. Le produit des cotes
explicites des jambes doit correspondre à la cote retenue du combiné.
Il faut au moins deux jambes, chacune reliée à une contribution pré-match et
à son dernier résultat prouvé. Fournir ces entités via `evaluate(..., leg_evidence=...)`;
sans elles, l'évaluation reste en attente. Le journal les vérifie à l'ajout.
L'issue du combiné doit correspondre au retour des jambes. Une ligne sur
`1N2`/`1X2`/`qualification`, ou un total négatif, reste en attente.
Règle absente, période non prise en charge, qualifié inconnu, cote de jambe
manquante ou report sans remboursement documenté : `en_attente`.
Un résultat en attente peut être finalisé par ajout avec `previous_result_id`.
Une correction d'un résultat déjà réglé exige aussi `audit_evidence_sha256`.

`reprise_groups` ne joint que les reprises attestées. `origin_groups` expose
les origines non résolues, y compris les cycles ; la similarité reste un indice.
La provenance d'une publication Robin n'est jamais réécrite. Groupes de reprises
et nombre de matchs distincts sont comptés séparément.
Les métriques dédupliquent les reprises par groupe, match, marché, sélection
et catégorie, avant toute somme ou moyenne. Les liens transitifs sont calculés
sur toutes les contributions, y compris celles d'autres auteurs non évaluées.

`IdentityRevision` exige `certainty='attestee'` pour appliquer les affectations;
la similarité seule ne fusionne rien. Une fusion
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
`rankings(..., at=...)` calcule ces mesures depuis le journal, avec les fenêtres,
les sources de l'auteur et les seules observations connues à cette date.
Une évaluation manquante du dernier résultat bloque le rapport au lieu de
faire disparaître un résultat. Sans date explicite, le statut reste en observation
ou suspendu après retrait ; aucun ordonnanceur ni exécution de workload.

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
