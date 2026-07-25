# Déploiement privé du Cockpit

## État vérifié

La version privée 8 est déployée avec un accès `OWNER_ONLY`. Sa preuve
versionnée est conservée dans `configs/cockpit-private-deployment.json` :
version, date, commit source, hash du snapshot et run de backfill.

Le workflow GitHub 26 sait :

1. restaurer l’état historique ;
2. recalculer le forecast ;
3. générer un snapshot sans secret ;
4. construire et tester le frontend ;
5. publier l’artefact GitHub.

Il ne dispose pas d’un mécanisme officiellement supporté pour appeler le
connecteur Sites privé depuis GitHub Actions. Le connecteur Sites permet un
déploiement privé depuis l’environnement Codex, mais aucune API ou action
GitHub n’est inventée ni simulée.

## Fraîcheur

Le snapshot compare son `currentBackfillRunId` et son hash de données au run et
au hash réellement déployés :

- même run et même hash : `COCKPIT_PRIVATE_DEPLOYED` ;
- run ou hash différent : `COCKPIT_PRIVATE_STALE`.

L’artefact automatique reste disponible même lorsque la version privée est
`STALE`. Les dates de génération et de déploiement restent distinctes. Neon et
les secrets fournisseur ne sont jamais inclus dans le navigateur.

## Alternative privée automatisable

Une seule alternative est retenue pour décision ultérieure : Cloudflare
Pages/Workers avec intégration GitHub et Cloudflare Access. L’intégration Git
peut déployer automatiquement chaque push, tandis qu’Access peut restreindre
l’application au propriétaire :

- [Git integration — Cloudflare Pages](https://developers.cloudflare.com/pages/configuration/git-integration/) ;
- [Cloudflare Access for Workers](https://developers.cloudflare.com/changelog/post/2025-10-03-one-click-access-for-workers/).

Aucune migration vers cette alternative n’est autorisée sans validation
utilisateur.

## Audit du 25 juillet 2026

- version privée visible : 8 ;
- accès : `OWNER_ONLY` ;
- déploiement : `2026-07-25T08:39:14.638374+00:00` ;
- run de backfill déployé : `30150002144` ;
- dernier backfill contrôlé : `30154099512` ;
- dernier artefact `main` : run `30155451951`, artefact `8618862988` ;
- statut attendu : `COCKPIT_PRIVATE_STALE`.

Le workflow corrigé publie le hash exact du snapshot et le hash de données,
mais ne déclenche pas de déploiement Sites. La version 8 reste intacte tant
qu’aucune migration d’hébergement ou publication manuelle n’est autorisée.
