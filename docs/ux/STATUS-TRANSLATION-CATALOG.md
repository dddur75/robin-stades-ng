# Catalogue de présentation des statuts

Source exécutable : `cockpit/app/i18n/status-translations.ts`.

Chaque entrée contient : traduction courte, explication longue, tonalité, icône, gravité de 0 à 3 et action éventuelle. Le badge associe toujours texte et symbole à la couleur. Le code d’origine n’est rendu que par les composants protégés par la Vue expert.

| Code interne | Libellé public | Ton | Gravité | Action ou sens |
|---|---|---:|---:|---|
| `BLOCKED_BY_COVERAGE` | Données encore insuffisantes | attention | 1 | attendre les captures |
| `BLOCKED_BY_TEMPORALITY` | Horaire de disponibilité non prouvé | critique | 2 | vérifier la preuve temporelle |
| `WAITING_FOR_OBSERVATIONS` | En attente de nouvelles observations | information | 0 | collecte en cours |
| `LIVE_PROSPECTIVE_CAPTURE` | Observations pré-match en cours | information | 0 | aucune action publique |
| `PROSPECTIVE_GATES_ACCUMULATING` | Les données s’accumulent progressivement | recherche | 0 | seuil inchangé |
| `NO_DUE_WINDOW_SUCCESS` | Aucune capture nécessaire | positif | 0 | planificateur vérifié |
| `CAPTURED_EMPTY` | Capture effectuée, aucune information publiée | neutre | 0 | réponse valide mais vide |
| `MISSED_WINDOW` | Fenêtre de capture manquée | critique | 3 | examiner l’incident |
| `TEMPORALITY_FAILED` | Donnée reçue trop tard | critique | 2 | exclue de la preuve pré-match |
| `PRODUCTION_LOCKED` | Paris réels désactivés | positif | 0 | protection active |
| `STORAGE_PAUSED` | Collectes historiques secondaires suspendues | neutre | 0 | séparation opérationnelle |
| `P3_P4_PAUSED` | Tâches secondaires suspendues | neutre | 0 | priorités inchangées |
| `NO_CANDIDATE` | Aucun candidat actuellement | neutre | 0 | aucun assouplissement |
| `REJECTED` | Hypothèse rejetée | critique | 1 | critères non franchis |
| `NOT_DUE` | Pas encore nécessaire | neutre | 0 | attendre la fenêtre |
| `READY` | Prêt | positif | 0 | critères satisfaits |
| `PARTIAL` | Partiel | attention | 1 | une partie disponible |
| `PENDING` | À venir | neutre | 0 | étape planifiée |
| `REGISTERED` | Match enregistré | positif | 0 | registre prospectif |
| `CAPTURED` | Capture vérifiée | positif | 0 | provenance et empreinte présentes |
| `OBSERVED` | Donnée observée | positif | 0 | observation réelle datée |
| `QUALITY_BLOCKED` | Analyse suspendue par prudence | attention | 1 | qualité ou quantité insuffisante |
| `INSUFFICIENT_OBSERVATION` | Observations encore insuffisantes | attention | 1 | aucune conclusion |
| `NO_LIVE_SHADOW_DATA` | Aucun résultat prospectif publié | neutre | 0 | aucune décision simulée |
| `R2_REPLAY_VERIFIED` | Replay R2 vérifié | positif | 0 | aucun appel fournisseur |
| `RECONSTRUCTIBLE_FROM_R2` | Reconstruction R2 disponible | positif | 0 | registre reconstructible |
| `ACTIVE_AND_VERIFIED` | Actif et vérifié | positif | 0 | mécanisme contrôlé |
| `CONNECTED_AND_PERSISTED` | Connecté et persistant | positif | 0 | connexion vérifiée |
| `HASH_CHAIN_VERIFIED` | Chaîne de preuves vérifiée | positif | 0 | empreintes cohérentes |
| `LEDGER_VERIFIED` | Registre vérifié | positif | 0 | registre public cohérent |
| `PASS` | Contrôle réussi | positif | 0 | seuil satisfait |
| `PASSED` | Contrôle réussi | positif | 0 | variante de source |
| `FAILED` | Contrôle en échec | critique | 2 | critère non satisfait |
| `ERROR` | Erreur technique | critique | 3 | consulter l’incident |
| `NO_PROMOTION` | Aucune promotion | neutre | 0 | aucun résultat admissible |
| `INCONCLUSIVE` | Résultat non concluant | neutre | 0 | données indécisives |

## Fallback

Tout code inconnu devient « État technique disponible » en Vue essentielle. Le texte long indique que le détail est réservé à Expert. Cette stratégie ferme la fuite de codes sans maquiller l’existence d’un état inconnu.

## Tonalités

- `positive` : vérification ou protection active, pas gain financier.
- `information` : collecte normale.
- `attention` : manque de preuve sans incident grave.
- `critical` : erreur, retard ou invalidité.
- `neutral` : non dû, absent ou non applicable.
- `research` : progression scientifique sans conclusion.
