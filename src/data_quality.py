"""
data_quality.py 
========================================================
Ce module contient les fonctions de contrôle qualité utilisées avant et après la migration. 
On vérifie systématiquement que les données du CSV respectent les règles avant de les insérer dans Mongo,
puis on revérifie après insertion que rien n'a été perdu ou déformé.
"""

import logging # logging : module standard Python pour écrire des messages de suivi
import pandas as pd
logger = logging.getLogger("data_quality") # Crée un "logger"


def run_quality_checks(df: pd.DataFrame, expected_columns: list) -> dict:
    """Contrôle qualité exécuté sur le DataFrame source (avant migration)."""
    result = {"passed": True, "checks": {}} #dictionnaire de résultat qu'on va enrichir au fur et à mesure des vérifications.

    #1 - Colonnes attendues
    missing = set(expected_columns) - set(df.columns) #vérification des colonnes manquantes
    result["checks"]["missing_columns"] = list(missing) #listing colonnes manquantes
    if missing:
        result["passed"] = False

    #2 - Valeurs manquantes
    nulls = df.isnull().sum() # si > 0, valeur manquante
    nulls = nulls[nulls > 0].to_dict() # On ne garde que les colonnes où il y a au moins une valeur manquante
    result["checks"]["null_values"] = nulls

    # 3 - Doublons
    duplicates = int(df.duplicated().sum())
    result["checks"]["duplicate_rows"] = duplicates

    # 4 - Typage
    type_issues = {}
    if not pd.api.types.is_integer_dtype(df["Age"]): #Vérifie si la colonne "Age" est bien de type entier 
        type_issues["Age"] = str(df["Age"].dtype) #On note le type réel rencontré (converti en texte)
    if not pd.api.types.is_float_dtype(df["Billing Amount"]):
        type_issues["Billing Amount"] = str(df["Billing Amount"].dtype)
    if not pd.api.types.is_integer_dtype(df["Room Number"]):
        type_issues["Room Number"] = str(df["Room Number"].dtype)
    result["checks"]["type_issues"] = type_issues
    if type_issues:
        # Dictionnaire non vide = au moins un souci de type détecté.
        result["passed"] = False

    # 5 - Plages de valeurs cohérentes (ex: âge positif et réaliste)
    invalid_ages = int(((df["Age"] < 0) | (df["Age"] > 120)).sum())
    result["checks"]["invalid_ages"] = invalid_ages
    if invalid_ages:
        result["passed"] = False

    result["row_count"] = len(df) # Nombre total de lignes du df
    logger.info("Contrôle qualité (avant) : %s", result)
    return result


def compare_before_after(df: pd.DataFrame, collection) -> dict:     # collection : objet pymongo représentant une collection MongoDB
    """Compare le nombre de lignes source vs documents migrés + échantillon."""
    result = {"passed": True, "checks": {}}

    source_count = len(df) # Nombre de lignes côté source (csv avant migration)
    mongo_count = collection.count_documents({})
    result["checks"]["source_row_count"] = source_count
    result["checks"]["mongo_document_count"] = mongo_count
    result["checks"]["counts_match"] = source_count == mongo_count
    if source_count != mongo_count:
        result["passed"] = False
    # Vérification du nombre de ligne avant et après migration

    # Vérification d'un échantillon de documents (types + présence des clés)
    sample = collection.find_one() # Récupère un document au hasard
    required_keys = {
        "name", "age", "gender", "blood_type", "medical_condition",
        "admission", "discharge_date", "doctor", "hospital",
        "insurance_provider", "billing_amount", "medication", "test_results",
    }
    missing_keys = required_keys - set(sample.keys()) if sample else required_keys #soustraction des clés demandées par rapport à la collection
    result["checks"]["missing_keys_in_sample"] = list(missing_keys)#Si il y en a une, le lister
    if missing_keys:
        result["passed"] = False
    #vérification des clés manquantes 

    if sample:
        result["checks"]["sample_types_ok"] = (
            isinstance(sample.get("age"), int)
            and isinstance(sample.get("billing_amount"), float)
            and isinstance(sample.get("admission", {}).get("room_number"), int)
        )
        if not result["checks"]["sample_types_ok"]:
            result["passed"] = False
        #Vérification des types pour les int et float
    logger.info("Contrôle qualité (après) : %s", result)
    return result