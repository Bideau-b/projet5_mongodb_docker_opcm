# Recherches — Déploiement de MongoDB sur AWS

> Ce document présente le fruit des recherches menées pour préparer la suite du projet
> (déploiement cloud). **Aucun déploiement réel n'a été réalisé** à ce stade : il s'agit
> d'une étude des options disponibles chez AWS, destinée à alimenter la discussion avec le
> client et à préparer le chiffrage du projet.

---

## 1. Pourquoi passer au cloud ?

L'architecture actuelle (Docker en local) répond au besoin immédiat de conteneurisation et de
portabilité, mais présente des limites pour un usage en production :
- pas de haute disponibilité automatique (un seul nœud MongoDB) ;
- sauvegardes et supervision à gérer manuellement ;
- scalabilité horizontale limitée par la machine hôte.

Le stockage et les bases de données managées dans le cloud permettent de louer de la capacité de
calcul et de stockage à la demande, sans avoir à acheter et maintenir de serveurs physiques, avec
une facturation à l'usage et une élasticité automatique.

---

## 2. Créer un compte AWS et comprendre la tarification

- La création d'un compte AWS se fait via [aws.amazon.com](https://aws.amazon.com) (adresse
  e-mail, moyen de paiement, vérification d'identité). Un premier niveau d'usage gratuit
  ("AWS Free Tier") permet de tester plusieurs services sans frais pendant une période limitée.
- Le modèle de tarification AWS est **pay-as-you-go** (paiement à l'usage) : pas de coût fixe
  d'entrée, facturation à la seconde ou à l'heure selon les services, avec des remises possibles
  via des instances réservées ou des engagements de type Savings Plans pour les charges stables.
- Pour ce projet, les principaux postes de coût à anticiper seraient : les instances de base de
  données, le stockage, les I/O, le transfert de données sortant, et la capacité de calcul des
  conteneurs (ECS/Fargate).

## 3. Amazon RDS et Amazon DocumentDB : quelle option pour MongoDB ?

Un point de vigilance : **Amazon RDS ne propose pas nativement MongoDB** — RDS couvre des
moteurs relationnels (PostgreSQL, MySQL, MariaDB, SQL Server, Oracle) ainsi qu'Aurora. Pour un
usage MongoDB managé, le service AWS pertinent est **Amazon DocumentDB (with MongoDB
compatibility)**.

**Amazon DocumentDB** est un service de base de données documentaire, entièrement managé et compatible avec l'API MongoDB, ce qui permet de migrer une application MongoDB généralement sans changement de code ni interruption de service. Il prend en charge la charge administrative habituelle : application des correctifs, sauvegardes et supervision, tout en offrant une résilience accrue via des clusters globaux.

Concernant la tarification, DocumentDB fonctionne sur un modèle pay-as-you-go sans coût initial, facturé à la seconde (minimum de 10 minutes) pour la classe d'instance choisie, complété par un coût de stockage au Go/mois et un coût lié aux opérations d'entrée/sortie. À titre indicatif, une instance d'entrée de gamme démarre autour de 0,35 $/heure (environ 250 $/mois pour un db.r5.large), avec un stockage facturé environ 0,10 $/Go-mois — ces montants sont à valider sur la page tarifaire officielle AWS avant tout engagement, car ils évoluent régulièrement selon la région et la classe d'instance.

Une version plus récente du service (DocumentDB 5.0) apporte des évolutions intéressantes pour ce projet : un stockage étendu jusqu'à 128 Tio, un chiffrement au niveau des champs côté client, un mode serverless avec mise à l'échelle automatique du calcul selon la demande, et le support des transactions ACID multi-documents.

**Recommandation** : Amazon DocumentDB est le service le plus adapté pour héberger MongoDB de
façon managée sur AWS, en particulier grâce à sa compatibilité applicative (le script
`migrate.py` développé dans ce projet fonctionnerait sans modification, seule l'URI de connexion
changerait).

## 4. Déploiement d'un conteneur MongoDB sur Amazon ECS

Alternative à DocumentDB : héberger soi-même l'image `mongo` (celle utilisée dans notre
`docker-compose.yml`) sur **Amazon ECS**, avec le mode d'exécution **AWS Fargate** (serverless,
sans gestion de serveurs).

Points clés identifiés dans nos recherches :
- Un déploiement type s'appuie sur une définition de tâche ECS précisant l'image Docker
  (`mongo:7`), les ressources CPU/mémoire allouées, et **un volume persistant** — généralement
  Amazon EFS — pour que les données MongoDB survivent aux redémarrages du conteneur.
- Les bonnes pratiques de déploiement ECS/Fargate recommandent de stocker l'image dans Amazon ECR, définir les besoins CPU/mémoire, utiliser des rôles IAM pour les tâches plutôt que des identifiants en dur, activer les logs vers CloudWatch, et gérer les variables sensibles via AWS SSM Parameter Store.
- Pour une architecture à plusieurs services communicants, un guide récent recommande de répartir les composants sur plusieurs zones de disponibilité, de faire transiter le trafic externe par un Application Load Balancer, et de lire les identifiants depuis AWS Secrets Manager et AWS Systems Manager Parameter Store plutôt que de les coder en dur.

**Comparaison DocumentDB vs MongoDB conteneurisé sur ECS** :

| Critère                        | Amazon DocumentDB                          | MongoDB sur ECS/Fargate                     |
|----------------------------------|----------------------------------------------|-------------------------------------------------|
| Administration                  | Entièrement managée (patchs, sauvegardes)    | À la charge du client (image `mongo` standard)  |
| Compatibilité MongoDB            | Compatible API, pas 100% des fonctionnalités | MongoDB natif, 100% des fonctionnalités         |
| Effort de mise en œuvre          | Plus rapide à mettre en place                | Nécessite EFS, ALB, gestion réseau, IAM         |
| Coût                             | Facturation par instance + stockage + I/O    | Facturation par vCPU/mémoire Fargate + stockage |
| Recommandé pour                 | Production, besoin de service managé          | Besoin de contrôle total sur la version Mongo   |

Pour ce client, dont l'objectif principal est de **résoudre un problème de scalabilité sans
recruter d'expertise DBA supplémentaire**, **Amazon DocumentDB reste l'option recommandée**, avec
l'architecture ECS/Fargate en option de secours si des fonctionnalités MongoDB non supportées par
DocumentDB s'avéraient indispensables.

## 5. Stockage des fichiers sources : Amazon S3

**Amazon S3** (Simple Storage Service) serait utilisé pour :
- archiver les fichiers CSV sources reçus du client avant migration (traçabilité, rejouabilité) ;
- stocker les exports de sauvegarde de la base (en complément des snapshots natifs de
  DocumentDB) ;
- servir de zone de dépôt (« data lake » léger) si le client envoie régulièrement de nouveaux
  fichiers à intégrer.

S3 propose un stockage à la demande, sans limite de capacité anticipée à provisionner, avec
plusieurs classes de stockage (accès fréquent, peu fréquent, archivage) permettant d'optimiser
les coûts selon la fréquence d'accès aux fichiers.

## 6. Sauvegardes et supervision sur AWS

- **Sauvegardes** : Amazon DocumentDB propose des sauvegardes automatiques continues et des
  snapshots manuels, avec restauration à un point dans le temps (Point-in-Time Recovery). Ces
  sauvegardes peuvent être complétées par des exports périodiques vers Amazon S3 pour de
  l'archivage longue durée.
- **Supervision** : Amazon CloudWatch permet de suivre les métriques d'utilisation (CPU,
  mémoire, connexions, I/O) et de déclencher des alertes en cas d'anomalie. Pour une architecture
  ECS/Fargate, l'intégration à CloudWatch Container Insights permet également de surveiller la
  santé des conteneurs applicatifs.
- **Sécurité réseau** : dans les deux scénarios (DocumentDB ou ECS), la base de données doit être
  déployée dans un VPC privé, non accessible directement depuis Internet, avec un accès limité
  aux seuls services applicatifs autorisés (groupes de sécurité).

## 7. Synthèse et recommandation

| Besoin exprimé par le client         | Service AWS proposé                              |
|----------------------------------------|-----------------------------------------------------|
| Base de données MongoDB managée, scalable | **Amazon DocumentDB**                              |
| Alternative avec contrôle total sur MongoDB | Conteneur `mongo` sur **Amazon ECS (Fargate)** + EFS |
| Stockage des fichiers sources / sauvegardes | **Amazon S3**                                      |
| Supervision et alerting                | **Amazon CloudWatch**                              |
| Sécurité des identifiants              | **AWS Secrets Manager** / **SSM Parameter Store**   |

**Recommandation générale** : démarrer avec **Amazon DocumentDB** pour bénéficier rapidement
d'une base managée, hautement disponible et compatible avec le code déjà écrit dans ce projet,
tout en s'appuyant sur **S3** pour l'archivage des fichiers sources et **CloudWatch** pour la
supervision. Cette approche minimise l'effort opérationnel pour le client tout en répondant à son
besoin de scalabilité horizontale.

---

## Sources consultées
- AWS — Qu'est-ce que le stockage dans le cloud ? https://aws.amazon.com/fr/what-is/cloud-storage/
- AWS — Amazon DocumentDB (page produit et tarification officielle)
- AWS Database Blog — Déploiement de conteneurs ECS connectés à Amazon DocumentDB
- Articles techniques sur les bonnes pratiques ECS/Fargate (gestion des secrets, IAM, CloudWatch)

*Note : les tarifs cités sont indicatifs (constatés au moment de la rédaction) et doivent être
revérifiés sur la page officielle AWS avant toute décision engageante, les prix évoluant
régulièrement selon les régions et les mises à jour de service.*
