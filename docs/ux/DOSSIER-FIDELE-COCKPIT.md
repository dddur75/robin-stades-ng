# Dossier fidèle dans le cockpit privé

La sous-page de l’Espace Expert montre le périmètre du pilote Ligue 1, l’état des sources et les visites documentées. Le plan V4 d’octobre sert de référence historique. Un plan indique des créneaux prévus. Les visites, réussites et publications ne deviennent visibles qu’après rattachement d’un journal vérifié à ce plan.

## Mise en œuvre

1. Construire hors ligne une projection du plan V4 et, si disponible, de son journal. Vérifier le registre, l’empreinte du plan, le journal et le lien exact entre les visites et le plan. Exclure les contenus des publications, les extraits, les URL et les diagnostics bruts.
2. Rendre la projection dans `/expert/observatoire-sources`. Afficher les sources, le type d’accès déclaré lors de la préparation et l’état des visites. Distinguer journal absent et zéro documenté. Les chiffres de visites s’appuient sur le plan entier, y compris les créneaux sans reçu.
3. Vérifier un journal réduit, un journal incohérent, l’absence de journal, l’accès au menu et le rendu sur écran étroit. Le pilote maintient les auteurs en observation, selon C5.3 de ses critères.

L’écran reprend la politique privée du cockpit. L’export s’effectue depuis un poste de travail hors ligne. Le site ne lit pas le journal brut et ne déclenche pas le collecteur.

## Générer l’instantané

Depuis la racine du dépôt, avec Robin installé dans l’environnement Python :

```powershell
python cockpit/scripts/build-source-observatory-snapshot.py --output cockpit/app/source-observatory-snapshot.json
```

Cette commande vérifie et reproduit le plan historique V4. Les fichiers de plan et de registre sont comparés aux empreintes des octets Git, y compris sur un checkout Windows dont les fins de ligne sont CRLF. Le journal conserve ses octets exacts.

Pour publier des observations vérifiées dans une prochaine version, fournir ensemble `--journal`, `--journal-receipt` et `--journal-claim-id`. Le reçu JSON contient exactement `schema_version` (`source-observatory-journal-receipt-v1`), `claim_id`, `plan_sha256` et `journal_head`. Dans le graphe de preuves, la revendication référence cet artefact et son SHA-256 dans `hash`, utilise la portée `SOURCE_OBSERVATORY_PILOT_JOURNAL` et indique l’empreinte du plan dans `dataset_lineage_id`. Son statut doit être `VERIFIED`, avec au moins deux relecteurs distincts du registre Council. Un journal dont le reçu appartient à un autre plan, dont la source diffère ou dont un succès arrive après tous les coups d’envoi concernés est refusé.

L’instantané fourni ici contient le plan et les sources historiques. Le test de projection compare ce fichier au résultat régénéré. Le suivi des contributions détaillées et le rapport de recette C1–C6 dépendent des preuves d’un pilote réel.

## Proposition historique de reprise Ligue 1

La J12 du 27 au 29 novembre 2026 fournit une fenêtre future. Candidat de préparation du **lundi 23 novembre à 20 h 45** au **dimanche 29 novembre à 20 h 44** (heure de Paris), sous réserve de disponibilité du runner, de la conformité des sources et d’accord sur le plan final. Les horaires ci-dessous viennent du [programme officiel de la J12](https://ligue1.com/fr/articles/l1_article_5843-).

| Date | Heure de Paris | UTC | Matchs |
|---|---:|---:|---|
| 27 novembre | 20 h 45 | 19 h 45 | Brest – Paris FC |
| 28 novembre | 17 h 15 | 16 h 15 | Angers – Lens |
| 28 novembre | 20 h 45 | 19 h 45 | PSG – Lorient, Le Mans – Lille, Le Havre – Strasbourg, Nice – Troyes |
| 29 novembre | 15 h 00 | 14 h 00 | Auxerre – Marseille |
| 29 novembre | 17 h 15 | 16 h 15 | Toulouse – Rennes |
| 29 novembre | 20 h 45 | 19 h 45 | Lyon – Monaco |

**Essai hors réseau du dernier créneau.** Avec cinq sources fictives, deux réponses par visite et un départ une minute avant le coup d’envoi, les cinq visites passent à une seconde par réponse. À dix secondes par réponse, deux réussissent et trois se terminent hors délai. À vingt secondes par réponse, une seule réussit. Cette simulation justifie un réglage du dernier créneau selon la charge autorisée avant tout gel.

**À préparer avant autorisation.** Revoir les règles d’accès des sources candidates et les horaires officiels. Figer le registre exact, les visites, les empreintes et le plafond avant la fenêtre. Le projet de cadence reprend une visite toutes les six heures et un créneau une minute avant chaque coup d’envoi distinct. Tester hors réseau ce dernier créneau avec les délais du collecteur. Si la charge séquentielle ne tient pas, construire une proposition corrigée avant le gel. Documenter les sources exclues avant le gel. Après le gel, garder les visites en échec, bloquées ou sans reçu dans le dénominateur. Présenter la recette du pilote au regard de C1–C6 et conserver le verdict `PARTIAL` si un seuil manque.

Le lancement et tout changement de plan nécessitent la décision explicite prévue par `RCV3-20261026-SOURCE-OBSERVATORY-DOSSIER-FIDELE-PLAN-V4` dans le journal Council. Le plan d’octobre et sa répétition à blanc ne font pas office de preuve pour cette nouvelle fenêtre.

## Raccordement applicatif du pilote J12

La décision de David du 17 novembre autorise le pilote Forecast Record sur A9_Mega, du 26 novembre à 08 h 45 au 29 novembre à 20 h 45, heure de Paris. Le plan figé prévoit sept rencontres, 23 créneaux, 28 lectures de match et 23 lectures de robots.txt. Son SHA-256 est `e81c73a2b850d9b2b9a3a07a230c80e850428d6367a8d5a3a332fb4c467ebaea`. Le collecteur et sa tâche Windows continuent à écrire dans le paquet local autorisé.

L'application lit ce journal directement sur le poste. Les routes `/expert/tipsters` et `/expert/tipsters/[id]` montrent les attributions pseudonymisées, les pronostics, leur première lecture locale, la détection fournisseur et la publication déclarée lorsqu'elle existe. Les variantes observées restent consultables dans l'historique. La première version observée est affichée par défaut. Les reprises de lecture sont dédupliquées par rencontre et identifiant fournisseur. Une attribution historique `author_key` reste limitée à la publication et n'est pas fusionnée avec une clé d'attribution plus récente.

La route `/expert/admin-collecte` permet de filtrer les visites planifiées, en cours, interrompues, manquées, réussies, échouées, bloquées ou arrêtées. Chaque rafraîchissement lit une image du journal et vérifie le plan, l'autorisation, les empreintes, le chaînage, l'ordre des créneaux et l'antériorité au coup d'envoi. Une ligne en cours d'écriture produit un état temporaire. Une ligne complète altérée produit une erreur. L'écran conserve alors le dernier suivi vérifié, daté, et suspend son export. Le zéro de pronostics exige au moins une visite réussie et vérifiée. Le bilan JSON téléchargé est celui affiché et inclut sa référence de preuve et son graphe de provenance local.

Le serveur Vite local expose `GET /api/tipsters` avec contrôle de l'adresse loopback, de Host, d'Origin et de Fetch Metadata. L'appel Python emploie des arguments fixes, un délai de huit secondes, une limite de sortie et une seule projection simultanée. Le lecteur reste hors du chemin d'exécution du collecteur. Le navigateur rafraîchit les preuves toutes les trente secondes et au retour sur la fenêtre. Le build du Worker conserve une réponse d'indisponibilité locale et les écrans indiquent que la consultation nécessite Robin sur A9_Mega.

Pour ouvrir l'application sur le poste, exécuter `pwsh -File cockpit/scripts/start-local-robin.ps1` depuis la racine du dépôt, puis accéder à `http://127.0.0.1:4173/expert/tipsters` ou `http://127.0.0.1:4173/expert/admin-collecte`. Le script lance le serveur de développement local en arrière-plan avec les journaux dans `.ci/local-robin`. La commande directe est `pnpm dev -p 4173 -H 127.0.0.1` depuis `cockpit`. Par défaut, le lecteur utilise le dossier frère `pilote-tipsters-j12` et le Python de `.venv`. Les installations différentes peuvent définir côté serveur `ROBIN_TIPSTERS_DIRECTORY`, `ROBIN_TIPSTERS_PYTHON` et `ROBIN_TIPSTERS_PLAN_SHA256`. Ces paramètres restent hors du navigateur et des exports.

La recette de développement utilise des journaux synthétiques isolés pour les cas de pronostic, de correction, d'échec, de corruption et de lecture tardive. Le contrôle nominal sur le paquet autorisé vérifie l'état programmé avant les premières observations. La recette de développement et le résultat réel du pilote disposent de leurs propres preuves. La recette globale du Dossier fidèle reste soumise aux critères C1–C6 gelés.

## Préparation des sources candidates

La route `/expert/sources-tipsters` lit la totalité du registre CSV, avec ses sources manuelles et bloquées. Au 18 novembre, ce registre contient 74 entrées, réparties en 57 à construire, 14 manuelles et 3 bloquées. Forecast Record est présenté séparément comme fournisseur du pilote J12 autorisé.

Chaque fiche conserve son adresse, sa date de contrôle historique, ses conditions et ses limites. Le formulaire permet de préparer une adresse publique du même domaine, un format RSS/Atom, HTML ou manuel, une cadence entre 30 et 1 440 minutes, un plafond entre une et dix requêtes par visite et une note de 2 000 caractères. Les valeurs initiales proposées sont six heures et deux requêtes par visite. C0 a enregistré ces préparations pour les 74 sources sur A9_Mega. La disponibilité actuelle, les droits d'usage, l'extraction de pronostics et l'inclusion dans une nouvelle mission restent à établir pour chaque source.

Le fichier local `cockpit/.ci/tipsters-source-config/preparations.jsonl` conserve chaque modification avec son parent et son empreinte SHA-256. Le CSV versionné et le paquet du pilote J12 restent indépendants de ces réglages. L'application expose GET et PUT sur `/api/tipsters/sources` uniquement sur le poste local. PUT exige l'origine exacte, JSON, un corps de 16 Ko au plus et une révision attendue. Le verrou couvre la lecture de l'historique, la comparaison de révision et l'ajout synchronisé. Un conflit conserve le brouillon de l'utilisateur. Le bouton de rechargement remplace explicitement le brouillon par les valeurs enregistrées.

Le journal est plafonné à quatre millions d'octets. Une sauvegarde qui franchirait ce plafond est refusée avant l'ajout. Un journal tronqué ou altéré suspend les sauvegardes. Un arrêt forcé du processus peut laisser `preparations.lock`. La récupération exige alors de vérifier l'absence de sauvegarde active avant de retirer ce seul verrou. L'historique reste conservé pour inspection.

Les tests peuvent définir `ROBIN_TIPSTERS_SETTINGS_DIRECTORY` vers un dossier isolé. Cette variable est lue côté serveur. La recette couvre les 74 profils, la persistance, deux rédacteurs concurrents, les bornes, les origines étrangères, les conflits entre deux fenêtres, les brouillons et les quatre largeurs mobiles. Le lecteur d'écran physique reste à vérifier.

## Exécution et qualification des 57 connecteurs publics

Le module `src/robin/source_observatory/connectors.py` construit un profil individuel pour chacune des 57 lignes `a_construire`. Les profils réutilisent les lecteurs RSS, Atom, HTML, articles JSON-LD et forums. Une attribution doit figurer explicitement dans l'entrée du flux ou dans le même article. Le nom de l'éditeur, une navigation et un profil voisin ne constituent pas une identité de tipster. Les noms sont pseudonymisés par source. Les interfaces officielles absentes et les flux sur un autre domaine restent bloqués, avec un motif affiché.

L'exécution vérifie les robots et les conditions actuelles avant le contenu. La lecture conserve seulement des liens, dates, empreintes et faits structurés. Le texte fournisseur est traité en mémoire. Les restrictions constatées ferment la lecture. Les pages d'authentification, challenges, erreurs, redirections et documents trop volumineux ne sont pas interprétés comme du contenu. Les adresses TCP publiques sont vérifiées et épinglées, avec TLS et SNI ; le transport n'utilise ni proxy, cookie, compte, JavaScript ni suivi automatique de redirection.

Le paquet local `cockpit/.ci/tipsters-connectors` contient le manifeste à huit champs, le plan épinglé, les reçus chaînés dans `events.jsonl` et une projection régénérable. Chaque requête est réservée et synchronisée sur disque avant de partir. Le verrou exclusif couvre l'exécution ; une réservation interrompue n'est pas rejouée. Les plafonds de qualification sont 228 requêtes au total, quatre par source, deux millions d'octets par document, 40 secondes par transfert, 2 700 secondes cumulées et une expiration de mission. Les délais robots et les erreurs consomment leur budget. Un crash exige une inspection avant retrait du seul verrou abandonné.

Une première qualification a été suivie d'une correction de la restriction HTML catégorielle provisoire. La phase corrective réutilise des témoins de chemin robots âgés de moins d'une heure, vérifiés sous les sept fichiers exécutés historiques. Elle ne remet aucun compteur à zéro. Les nouvelles conditions sont lues avant le contenu, avec un délai conservateur de 60 secondes. Sa décision C0 doit être autorisante et liée aux empreintes exactes de la phase et de son prédécesseur. Les trois sources du premier canari et les sources closes dans la phase ne sont pas rejouées.

La consultation locale `GET /api/tipsters/connectors` n'effectue aucun appel fournisseur. Le lancement exige un `POST` JSON de même origine, un plan valide et le budget résiduel. Le Worker hébergé renvoie un état d'indisponibilité locale. L'admin distingue profils traités, sources avec publications, sélections résolues à rapprocher, extractions ambiguës et pronostics prouvés avant match. Les extractions ambiguës sont exclues des sélections, sans modification des observations historiques. Les attributions ouvrent leurs fiches de publications sur `/expert/tipsters/author%3A…`. Ces fiches indiquent explicitement que l'identité humaine n'est pas vérifiée et n'affichent aucun score de performance.

Le script `cockpit/scripts/run-tipster-connectors.py --directory <paquet-local>` régénère la vue hors réseau. `--init` prépare un nouveau manifeste et des empreintes dans un dossier neuf ; `--run` exécute uniquement les profils et le budget de ce plan, après validation des clés de contrôle. Le chemin serveur par défaut peut être remplacé avec `ROBIN_CONNECTORS_DIRECTORY`. Les paramètres préparatoires de l'éditeur restent indépendants : leur adoption demande un nouveau plan épinglé, elle ne modifie jamais une campagne en cours.

Les reçus réels et les limites de cette qualification figurent dans `reports/ux/TIPSTER-CONNECTORS-RECETTE-20261118.json`. Une source lisible ou un article collecté ne constitue pas un pronostic humain. La livraison complète des tipsters reste `PARTIAL` tant que l'attribution humaine, la sélection, le match et l'antériorité au coup d'envoi ne sont pas prouvés. Cette qualification finie n'est pas une collecte récurrente. Le pilote Forecast Record J12 conserve ses fichiers, sa tâche et son budget distinct de 51 requêtes.
