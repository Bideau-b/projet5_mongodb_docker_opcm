"""
migrate.py
===================================================
Script principal : lit le CSV, le nettoie, vérifie sa qualité, puis
migre les données vers MongoDB, crée les index, revérifie la qualité,
et écrit un rapport JSON de la migration.
"""

import os
import sys #sys.exit() et sys.stdout pour les logs
import json #sérialisation du rapport de migration en fichier .json
import logging
from datetime import datetime, timezone
import pandas as pd
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import ConnectionFailure, BulkWriteError
# MongoClient : objet de connexion à un serveur Mongo.
# ASCENDING/DESCENDING : constantes utilisées pour définir le sens de tri
# d'un index (1 ou -1 en interne).
# ConnectionFailure : exception levée si la connexion à Mongo échoue
# BulkWriteError : exception levée si une insertion en masse échoue partiellement
from data_quality import run_quality_checks, compare_before_after

# --------------------------------------------------------------------------- #
# Configuration
# --------------------------------------------------------------------------- #

logging.basicConfig( #config log
    level=logging.INFO, #affiche les messages info, les warning et les error
    format="%(asctime)s | %(levelname)-8s | %(message)s", # format : gabarit d'affichage -> date/heure | NIVEAU   | message
    handlers=[
        logging.StreamHandler(sys.stdout),#dans la console
        logging.FileHandler("/app/logs/migration.log", mode="a") if os.path.isdir("/app/logs") else logging.NullHandler(), #ecriture dans migration.log
    ],
)
logger = logging.getLogger("migrate")

MONGO_HOST = os.getenv("MONGO_HOST", "localhost")
MONGO_PORT = os.getenv("MONGO_PORT", "27017")
MONGO_DB = os.getenv("MONGO_DB", "healthcare_db")
MONGO_USER = os.getenv("MONGO_USER", "migration_user")
MONGO_PASSWORD = os.getenv("MONGO_PASSWORD", "changeme")
MONGO_AUTH_SOURCE = os.getenv("MONGO_AUTH_SOURCE", "healthcare_db")
CSV_PATH = os.getenv("CSV_PATH", "/data/healthcare_dataset.csv")
BATCH_SIZE = int(os.getenv("BATCH_SIZE", "5000"))
COLLECTION_NAME = "patients"

EXPECTED_COLUMNS = [
    "Name", "Age", "Gender", "Blood Type", "Medical Condition",
    "Date of Admission", "Doctor", "Hospital", "Insurance Provider",
    "Billing Amount", "Room Number", "Admission Type", "Discharge Date",
    "Medication", "Test Results",
]
#liste de référence des colonnes attendues dans le CSV, pour valider le fichier source et pour le contrôle qualité.

DUPLICATE_STAY_SUBSET = ["Name", "Date of Admission", "Doctor", "Hospital", "Billing Amount"]
# Colonnes utilisé pour détecter les doublons


def get_mongo_uri() -> str:
    """Construit l'URI de connexion MongoDB avec authentification."""
    return (
        f"mongodb://{MONGO_USER}:{MONGO_PASSWORD}@{MONGO_HOST}:{MONGO_PORT}/"
        f"{MONGO_DB}?authSource={MONGO_AUTH_SOURCE}"
    )


def load_and_clean_csv(csv_path: str) -> pd.DataFrame:
    """Charge le CSV et applique le nettoyage validé lors de l'analyse exploratoire (...)"""
    logger.info("Lecture du fichier CSV : %s", csv_path)
    df = pd.read_csv(csv_path)

    #colonnes manquantes
    missing_cols = set(EXPECTED_COLUMNS) - set(df.columns)
    if missing_cols:
        raise ValueError(f"Colonnes manquantes dans le CSV : {missing_cols}")

    # Normalisation des chaînes de caractères (casse incohérente dans la source, ex: "Bobby JacksOn")
    df["Name"] = df["Name"].astype(str).str.strip().str.title() #mise en forme du name
    for col in ["Gender", "Blood Type", "Medical Condition", "Doctor",
                "Hospital", "Insurance Provider", "Admission Type",
                "Medication", "Test Results"]:
        df[col] = df[col].astype(str).str.strip() #mise ne forme des colonnes string

    # Typage explicite
    df["Age"] = df["Age"].astype(int)
    df["Room Number"] = df["Room Number"].astype(int)
    df["Billing Amount"] = df["Billing Amount"].astype(float)
    df["Date of Admission"] = pd.to_datetime(df["Date of Admission"], errors="coerce")
    df["Discharge Date"] = pd.to_datetime(df["Discharge Date"], errors="coerce")

    #1 - Doublons strictement identiques (toutes colonnes)
    before = len(df)
    df = df.drop_duplicates() #suppression des doublons identiques
    removed_exact = before - len(df)
    if removed_exact:
        logger.warning("Doublons stricts supprimés : %d", removed_exact)
    # Comptage des doublons exacts qui ont été supprimés, et on le logge si > 0.

    #2 - Doublons "même séjour, âge différent" : on garde la première occurrence.
    before = len(df)
    df = df.drop_duplicates(subset=DUPLICATE_STAY_SUBSET, keep="first") #suppression des ages diffirents seulement, les homonymes sont gardés
    removed_age_dupes = before - len(df)
    if removed_age_dupes:
        logger.warning("Doublons 'même séjour, âge différent' supprimés : %d", removed_age_dupes)

    #3 - Montants de facturation négatifs retirés
    before = len(df)
    df = df[df["Billing Amount"] >= 0]
    removed_negative_billing = before - len(df)
    if removed_negative_billing:
        logger.warning("Lignes à montant de facturation négatif supprimées : %d", removed_negative_billing)

    # Log récap final
    logger.info(
        "Nettoyage terminé : %d lignes restantes "
        "(doublons stricts supprimés: %d, doublons 'âge' supprimés: %d, montants négatifs supprimés: %d)",
        len(df), removed_exact, removed_age_dupes, removed_negative_billing,
    )

    return df

#construction du document pour Mongo
def dataframe_to_documents(df: pd.DataFrame) -> list:
    """Convertit chaque ligne du DataFrame en document MongoDB (dict)"""
    documents = []
    for record in df.to_dict(orient="records"):
        doc = {
            "name": record["Name"],
            "age": int(record["Age"]),
            "gender": record["Gender"],
            "blood_type": record["Blood Type"],
            "medical_condition": record["Medical Condition"],
            "admission": {
                "date": record["Date of Admission"].to_pydatetime()
                if pd.notnull(record["Date of Admission"]) else None,
                "type": record["Admission Type"],
                "room_number": int(record["Room Number"]),
            },
            "discharge_date": record["Discharge Date"].to_pydatetime()
            if pd.notnull(record["Discharge Date"]) else None,
            "doctor": record["Doctor"],
            "hospital": record["Hospital"],
            "insurance_provider": record["Insurance Provider"],
            "billing_amount": float(record["Billing Amount"]),
            "medication": record["Medication"],
            "test_results": record["Test Results"],
            "migrated_at": datetime.now(timezone.utc),
        }
        documents.append(doc)
    return documents

#Création des index
def create_indexes(collection):
    """Crée les index pertinents pour les usages fréquents du client.""" #pour les filtres/tris
    logger.info("Création des index...")
    collection.create_index([("name", ASCENDING)])
    collection.create_index([("medical_condition", ASCENDING)])
    collection.create_index([("admission.date", DESCENDING)])
    collection.create_index([("doctor", ASCENDING)])
    collection.create_index([("insurance_provider", ASCENDING)])
    collection.create_index([("hospital", ASCENDING), ("medical_condition", ASCENDING)]) #index composé
    logger.info("Index créés : %s", collection.index_information().keys()) #log index

#Insersion des documents dans Mongo
def insert_in_batches(collection, documents: list, batch_size: int):
    """Insère les documents par lots pour limiter la charge mémoire/réseau."""
    total = len(documents)
    inserted = 0
    for i in range(0, total, batch_size): # batch_size (ex: 0, 5000, 10000)
        batch = documents[i:i + batch_size]
        try:
            collection.insert_many(batch, ordered=False) #insersion 
            inserted += len(batch)
            logger.info("Inséré %d / %d documents", inserted, total)
        except BulkWriteError as bwe:
            logger.error("Erreur d'insertion sur un lot : %s", bwe.details) #log pour document non inséré 
    return inserted


def main():
    report = {"started_at": datetime.now(timezone.utc).isoformat()}

    #1 - Chargement + nettoyage
    df = load_and_clean_csv(CSV_PATH)

    #2 - Contrôle qualité avant migration
    logger.info("Contrôle qualité (avant migration)")
    quality_before = run_quality_checks(df, EXPECTED_COLUMNS)
    report["quality_before"] = quality_before
    if not quality_before["passed"]:
        logger.error("Le contrôle qualité a échoué, la migration est interrompue.")
        logger.error(json.dumps(quality_before, indent=2, default=str))
        sys.exit(1)


    # 3. Connexion MongoDB
    logger.info("Connexion à MongoDB (%s:%s, base=%s)...", MONGO_HOST, MONGO_PORT, MONGO_DB)
    client = MongoClient(get_mongo_uri(), serverSelectionTimeoutMS=10000) # sous 10 secondes, erreur si ne répond pas 
    
    #test ping connexion Mongo
    try:
        client.admin.command("ping")
    except ConnectionFailure as exc:
        logger.error("Impossible de se connecter à MongoDB : %s", exc)
        sys.exit(1)


    db = client[MONGO_DB]
    collection = db[COLLECTION_NAME]

    # vérification collection déjà présente
    existing_count = collection.count_documents({})
    if existing_count:
        logger.warning("La collection contient déjà %d documents, elle va être vidée avant migration.", existing_count)
        collection.delete_many({}) #suppression si déjà présent

    #4 - Conversion + insertion
    documents = dataframe_to_documents(df)
    inserted = insert_in_batches(collection, documents, BATCH_SIZE)
    report["documents_inserted"] = inserted

    #5 - Index
    create_indexes(collection)

    #6 - Contrôle qualité après migration
    logger.info("Contrôle qualité (après migration)")
    quality_after = compare_before_after(df, collection)
    report["quality_after"] = quality_after
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    report["status"] = "success" if quality_after["passed"] else "warning"

    os.makedirs("/app/logs", exist_ok=True) if os.path.isdir("/app") else None #créa dossier si non existant
    report_path = "/app/logs/migration_report.json" if os.path.isdir("/app/logs") else "migration_report.json" #rapport écrit dans /app/logs si on est dans Docker, sinon dans le dossier local
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str, ensure_ascii=False)
    logger.info("Migration terminée. Rapport enregistré dans %s", report_path)
    logger.info(json.dumps(report, indent=2, default=str, ensure_ascii=False))
    client.close() #Fermeture client


if __name__ == "__main__":
    main()
#le code sous ce "if" ne s'exécute QUE si le fichier est lancé directement (python migrate.py), pas s'il est importé comme module depuis un autre
#script (ex: test_migration.py qui importe des fonctions de ce fichier sans vouloir lancer main()).