# Plan local — ronde 2 puis T7

**Rédacteur unique :** Codex, branche `codex/observatoire-sources-v2`, aucun commit.
**Spécification :** demande de David, revue Gemini ronde 2, registre et critères gelés du pilote.
**Architecture :** prolonger les dataclasses et le journal existants ; collecteur Python avec transport HTTP injectable. Flux publics RSS/Atom et articles HTML reconnus, aucune exploration de liens privés ni de connexion. Payloads immuables dans le répertoire externe désigné par `SOURCE_OBSERVATORY_RAW_DIR`.

- [x] A : reproduire les huit constats ; correctifs minimaux ; tests de domaine. Réponse détaillée dans `reponse-revue-gemini-ronde2.md`.
- [x] B : tests du plan déterministe (29/10, cadence maximale 6 h, arrêts par coup d'envoi), des états de registre, CGU et robots, des erreurs HTTP, temps plateforme absents, versions et payloads hors Git.
- [x] B : `collector.py` et ajout minimal de métadonnées de visite au modèle/store existants. Plan JSON et horaires sourcés ; `--dry-run` sans HTTP ni fausse réussite ; exécution ponctuelle des seules visites dues, aucune installation de tâche système.
- [x] Recette technique : 312 tests, lint, typage, sécurité ciblée, contraintes de chemins et noms ; rapport et preuves. Sans commit, push, API-Football, pari ou publication. Relecture indépendante tentée, indisponible : acceptation PARTIAL.

**Décision technique :** conserver les sources manuelles dans le plan et le dénominateur ; elles restent en échec documenté sans collecte automatisée. CGU restrictives ou inconnues : aucune lecture automatisée du contenu. Adapter seulement les flux/pages explicitement publics ; format inconnu = échec documenté, jamais succès vide par défaut. Toute redirection est refusée, pas de cookies ou authentification.

**Temps :** UTC à l'exécution, fuseau d'origine conservé par le store. L'heure plateforme n'est jamais déduite d'un en-tête HTTP ou de la date de visite. Le plan conserve les échéances manquées ; un run tardif les journalise en échec plutôt que de les remplacer par une observation actuelle.

**Relecture :** autre fournisseur requis pour accepter la livraison ; pas d'auto-validation ni de montée en charge si indisponible. Tests synthétiques seulement, aucun replay du corpus.
