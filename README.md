# Migration de données médicales vers MongoDB (Docker)

Projet réalisé pour **DataSoluTech** — migration d'un dataset médical (CSV, ~55 500 lignes)
d'un client vers une base **MongoDB** conteneurisée, dans une optique de scalabilité horizontale
Première étape avant un déploiement cloud AWS.

---

## 1. Contexte

Le client dispose d'un export CSV de données patients (`healthcare_dataset.csv`, 15 colonnes,
55 500 lignes) et rencontre des difficultés de scalabilité avec son système actuel. L'objectif
de ce projet est de :

1. Analyser puis migrer ces données vers une base NoSQL orientée documents (MongoDB), mieux adaptée à la
   montée en charge horizontale et à l'évolution future du schéma de données.
2. Conteneuriser l'ensemble (base de données + script de migration) avec Docker pour
   garantir la portabilité et la reproductibilité de l'environnement.
3. Documenter les options de déploiement sur AWS pour la suite du projet.

---

## 2. Aperçu du dataset source

| Colonne              | Type source | Exemple                  |
|-----------------------|-------------|---------------------------|
| Name                  | texte       | Bobby JacksOn             |
| Age                   | entier      | 30                        |
| Gender                | texte       | Male / Female             |
| Blood Type            | texte       | B-, A+, O+...             |
| Medical Condition     | texte       | Cancer, Obesity...        |
| Date of Admission     | date        | 2024-01-31                |
| Doctor                | texte       | Matthew Smith             |
| Hospital              | texte       | Sons and Miller           |
| Insurance Provider    | texte       | Blue Cross, Medicare...   |
| Billing Amount        | décimal     | 18856.28                  |
| Room Number           | entier      | 328                       |
| Admission Type        | texte       | Urgent / Emergency / Elective |
| Discharge Date        | date        | 2024-02-02                |
| Medication            | texte       | Paracetamol                |
| Test Results          | texte       | Normal / Abnormal / Inconclusive |

Constats du diagnostic initial (voir `data_quality.py`) : 
- aucune valeur manquante, 
- 534 lignes strictement dupliquées
- 40
Ces deux derniers points sont corrigés lors de l'étape de nettoyage.

---

## 3. Schéma de la base de données MongoDB

### Base : `healthcare_db` — Collection : `patients`

Le choix a été fait de **dénormaliser légèrement** le document en regroupant les informations
liées au séjour hospitalier (date d'admission, type d'admission, chambre) dans un sous-document
`admission`, ce qui reflète mieux la structure logique des données et facilite les requêtes
groupées (ex: "tous les patients admis en urgence dans telle chambre").

```json
{
  "_id": ObjectId("..."),
  "name": "Bobby Jackson",
  "age": 30,
  "gender": "Male",
  "blood_type": "B-",
  "medical_condition": "Cancer",
  "admission": {
    "date": ISODate("2024-01-31T00:00:00Z"),
    "type": "Urgent",
    "room_number": 328
  },
  "discharge_date": ISODate("2024-02-02T00:00:00Z"),
  "doctor": "Matthew Smith",
  "hospital": "Sons and Miller",
  "insurance_provider": "Blue Cross",
  "billing_amount": 18856.28,
  "medication": "Paracetamol",
  "test_results": "Normal",
  "migrated_at": ISODate("2026-09-04T10:00:00Z")
}
```

### Index créés (voir `create_indexes()` dans `src/migrate.py`)

| Index                                             | Justification                                                   |
|----------------------------------------------------|-------------------------------------------------------------------|
| `name`                                              | Recherche rapide d'un patient par nom                             |
| `medical_condition`                                 | Filtrage/statistiques par pathologie (cas d'usage fréquent client) |
| `admission.date` (décroissant)                      | Tri des admissions les plus récentes, tableaux de bord            |
| `doctor`                                            | Recherche de tous les patients suivis par un médecin              |
| `insurance_provider`                                | Filtrage par assureur (facturation)                                |
| Composé : `hospital` + `medical_condition`          | Cas d'usage type "patients de tel hôpital pour telle pathologie"   |

Un index composé permet de couvrir efficacement les requêtes filtrant sur les deux champs
simultanément, évitant un double scan ou un index intersection coûteux.

---

## 4. Authentification et rôles utilisateurs

L'authentification MongoDB est activée dès le premier démarrage du conteneur via le script
[`mongo-init/init-mongo.js`](mongo-init/init-mongo.js), exécuté automatiquement par l'image
officielle `mongo` (mécanisme `docker-entrypoint-initdb.d`).

Trois niveaux d'accès sont définis, selon le principe du moindre privilège :

| Utilisateur       | Rôle MongoDB          | Usage                                                              |
|--------------------|------------------------|----------------------------------------------------------------------|
| `admin` (root)     | `root` (super-utilisateur) | Administration du serveur uniquement (créé via les variables `MONGO_INITDB_ROOT_*`), jamais utilisé par l'application. |
| `migration_user`   | `readWrite` sur `healthcare_db` | Utilisé par le script Python de migration : insertion, mise à jour, création d'index. |
| `analyst_user`     | `read` sur `healthcare_db`      | Prévu pour les outils de reporting/BI du client : lecture seule, aucune modification possible. |

Les identifiants sont injectés via des variables d'environnement (fichier `.env`, non
versionné — voir `.env.example`) et ne sont jamais codés en dur dans les scripts. En production,
il est recommandé de :
- remplacer les mots de passe par défaut,
- utiliser un gestionnaire de secrets (AWS Secrets Manager, Docker Secrets, Vault...),
- activer TLS/SSL pour les connexions au cluster MongoDB.

---

## 5. Architecture des conteneurs

```
┌──────────────────────────┐                 ┌───────────────────────────────┐
│   Conteneur "mongodb"    │                 │   Conteneur "migration"       │
│   image: mongo:7.0       │◄────────────────┤   image: build (Dockerfile)   │
│   - authentification     │  réseau         │   - Python 3.11 + pandas      │
│   - init-mongo.js        │ "healthcare-net"│   - pymongo                   │
│   port 27017 exposé      │                 │   - script migrate.py         │
└──────────┬───────────────┘                 └───────────────┬───────────────┘
           │ volume nommé                                    │ lecture seule
           ▼                                                 ▼
      mongo-data                              ./data/healthcare_dataset.csv
                                              volume nommé : migration-logs
```

- **Volume `mongo-data`** : persiste les données MongoDB même après un `docker-compose down`.
- **Bind mount `./data`** : expose le CSV source au conteneur de migration (lecture seule).
- **Volume `migration-logs`** : conserve les logs et le rapport JSON de migration.
- **Réseau bridge dédié** (`healthcare-net`) : isole la communication entre les deux conteneurs.

---

## 6. Installation et exécution

### Prérequis
- Docker et Docker Compose installés.
- Le fichier `healthcare_dataset.csv` placé dans le dossier `data/`.

### Étapes

```bash
# 1. Cloner le dépôt
git clone <url-du-repo>
cd healthcare-mongodb-migration

# 2. Configurer les variables d'environnement
cp .env.example .env
# éditer .env si besoin (mots de passe, etc.)

# 3. Placer le CSV source
cp /chemin/vers/healthcare_dataset.csv data/

# 4. Lancer MongoDB + la migration
docker-compose up --build
```

Ce que fait `docker-compose up` :
1. Démarre le conteneur `mongodb`, qui exécute `init-mongo.js` au premier lancement
   (création de la base et des utilisateurs).
2. Attend que MongoDB soit opérationnel (`healthcheck`).
3. Construit et démarre le conteneur `migration`, qui exécute `src/migrate.py` :
   - lecture et nettoyage du CSV,
   - contrôle qualité **avant** migration,
   - insertion des documents par lots dans la collection `patients`,
   - création des index,
   - contrôle qualité **après** migration (comparaison des comptages, échantillon),
   - écriture d'un rapport `migration_report.json` dans le volume `migration-logs`.

### Vérifier que la migration a fonctionné

```bash
docker exec -it healthcare_mongodb mongosh -u migration_user -p changeme \
  --authenticationDatabase healthcare_db healthcare_db

# dans le shell mongo :
db.patients.countDocuments()
db.patients.findOne()
db.patients.getIndexes()
```

### Relancer uniquement la migration (sans recréer Mongo)

```bash
docker-compose run --rm migration
```

Le script est **idempotent** : il vide la collection `patients` avant chaque insertion complète,
évitant les doublons en cas de ré-exécution.

---

## 7. Tests automatisés

Les tests unitaires (`pytest`) couvrent le contrôle qualité et la transformation des données
(sans nécessiter de connexion MongoDB réelle, grâce à un mock pour `compare_before_after`) :

```bash
pip install -r requirements.txt
pytest tests/ -v
```

11 tests couvrent : détection de colonnes manquantes, doublons, valeurs incohérentes (âge),
conversion correcte des types, structure du document Mongo (`admission` imbriqué), et
correspondance des comptages avant/après migration.

---

## 8. Structure du dépôt

```
healthcare-mongodb-migration/
├── README.md
├── requirements.txt
├── docker-compose.yml
├── Dockerfile
├── .env.example
├── .gitignore
├── data/
│   └── healthcare_dataset.csv     # non versionné en pratique (voir .gitignore projet réel)
├── mongo-init/
│   └── init-mongo.js              # création base + utilisateurs/rôles
├── src/
│   ├── migrate.py                 # script principal de migration
│   └── data_quality.py            # contrôles qualité avant/après
├── tests/
│   └── test_migration.py          # tests pytest
└── docs/
    ├── schema.md                  # schéma détaillé (extrait de ce README)
    └── aws_research.md            # recherches sur le déploiement AWS
```

---

## 9. Prochaines étapes

Voir [`docs/aws_research.md`](docs/aws_research.md) pour l'étude des options de déploiement
cloud (Amazon DocumentDB, ECS, S3, sauvegardes/monitoring) qui permettront de faire évoluer
cette architecture Docker locale vers une solution managée et hautement disponible sur AWS.
