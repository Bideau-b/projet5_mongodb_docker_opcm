# Schéma de la base de données MongoDB

## Base de données : `healthcare_db`
## Collection : `patients`

### Pourquoi un modèle orienté document plutôt que relationnel ?

Le dataset source est une table plate unique (pas de relations multi-tables), mais certains
champs sont **fonctionnellement liés** (date d'admission, type d'admission, numéro de chambre
décrivent tous le même "événement d'hospitalisation"). MongoDB permet de représenter cela
naturellement via un **sous-document**, sans jointure, ce qui :

- accélère les lectures les plus fréquentes (un seul document = une seule lecture disque/mémoire) ;
- facilite l'évolution du schéma (ajout futur de champs comme des sous-documents "vitals" ou
  "historique de facturation" sans migration lourde) ;
- s'aligne avec le besoin de scalabilité horizontale exprimé par le client (sharding possible sur
  `_id` ou sur un champ métier comme `hospital`).

### Modèle de document

| Champ                     | Type BSON   | Description                                             |
|----------------------------|-------------|----------------------------------------------------------|
| `_id`                       | ObjectId    | Identifiant unique généré par MongoDB                     |
| `name`                      | string      | Nom du patient (normalisé en "Title Case")                |
| `age`                       | int32       | Âge du patient                                             |
| `gender`                    | string      | "Male" / "Female"                                          |
| `blood_type`                | string      | Groupe sanguin                                             |
| `medical_condition`         | string      | Pathologie diagnostiquée                                   |
| `admission.date`            | date        | Date d'admission                                           |
| `admission.type`            | string      | "Urgent" / "Emergency" / "Elective"                        |
| `admission.room_number`     | int32       | Numéro de chambre                                           |
| `discharge_date`            | date        | Date de sortie                                              |
| `doctor`                    | string      | Médecin traitant                                            |
| `hospital`                  | string      | Établissement                                                |
| `insurance_provider`        | string      | Assureur                                                     |
| `billing_amount`            | double      | Montant facturé                                              |
| `medication`                | string      | Médicament prescrit                                          |
| `test_results`              | string      | "Normal" / "Abnormal" / "Inconclusive"                       |
| `migrated_at`               | date        | Horodatage technique de la migration (traçabilité)           |

### Index

Voir le tableau détaillé dans le [README](../README.md#3-schéma-de-la-base-de-données-mongodb).
Les index sont créés par le script `src/migrate.py` (fonction `create_indexes`) et sont donc
reproductibles à chaque exécution de la migration.

### Évolutivité (scalabilité horizontale)

Pour anticiper la montée en charge évoquée par le client :
- **Sharding** : la collection pourrait être partitionnée (shardée) sur `hospital` ou sur un
  hachage de `_id` si le volume de données augmente fortement, répartissant la charge sur
  plusieurs nœuds MongoDB.
- **Réplication** : un *replica set* (même en local, 3 nœuds minimum) apporterait la haute
  disponibilité et la tolérance aux pannes, complémentaire du sharding.
- Ces deux aspects sont approfondis côté cloud dans `aws_research.md` (Amazon DocumentDB gère
  nativement la réplication et propose du scaling de stockage/lecture).
