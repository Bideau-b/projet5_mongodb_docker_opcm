"""
test_migration.py
===========================================================
Suite de tests automatisés avec pytest. L'objectif : vérifier que 
chaque fonction (nettoyage, contrôle qualité, transformation en
documents Mongo) se comporte comme prévu, sans avoir besoin d'un
vrai serveur MongoDB qui tourne (on simule la collection Mongo).
"""

import sys
import os
from unittest.mock import MagicMock #  imite le comportement de la collection pymongo 

import pandas as pd
import pytest #détecte automatiquement les fonctions dont le nom commence par "test_" et les classes dont le nom commence par "Test", et les exécute une par une

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
# Bricolage classique pour que Python trouve les modules à tester.
# os.path.dirname(__file__) : dossier où se trouve CE fichier de test.
# os.path.join(..., "..", "src") : remonte d'un dossier puis va dans "src"
# (donc si les tests sont dans tests/ et le code dans src/, ça pointe
# vers src/ depuis tests/).
# sys.path.insert(0, ...) : ajoute ce chemin en PREMIÈRE position dans
# la liste des dossiers où Python cherche les modules à importer

from data_quality import run_quality_checks, compare_before_after #import des traitements des données
from migrate import load_and_clean_csv, dataframe_to_documents, EXPECTED_COLUMNS #import des fonctions de migration


@pytest.fixture #transforme la fonction en données réutilisable pour chaque test
def sample_df():
    return pd.DataFrame({
        "Name": ["John Doe", "Jane Smith"],
        "Age": [45, 30],
        "Gender": ["Male", "Female"],
        "Blood Type": ["A+", "O-"],
        "Medical Condition": ["Diabetes", "Asthma"],
        "Date of Admission": ["2023-01-01", "2023-02-15"],
        "Doctor": ["Dr. Alice", "Dr. Bob"],
        "Hospital": ["General Hospital", "City Clinic"],
        "Insurance Provider": ["Aetna", "Cigna"],
        "Billing Amount": [1000.50, 2500.75],
        "Room Number": [101, 202],
        "Admission Type": ["Urgent", "Elective"],
        "Discharge Date": ["2023-01-05", "2023-02-20"],
        "Medication": ["Metformin", "Albuterol"],
        "Test Results": ["Normal", "Abnormal"],
    })



class TestQualité: #on met ces classes pour trier les tests

    def test_passes_on_clean_data(self, sample_df):
        result = run_quality_checks(sample_df, EXPECTED_COLUMNS)
        assert result["passed"] is True
        assert result["checks"]["duplicate_rows"] == 0
        assert result["row_count"] == 2
        # test des contrôles de qualité

    def test_detects_missing_column(self, sample_df):
        df = sample_df.drop(columns=["Doctor"])
        result = run_quality_checks(df, EXPECTED_COLUMNS)
        assert result["passed"] is False
        assert "Doctor" in result["checks"]["missing_columns"]
        #Vérifie que le contrôle qualité détecte bien qu'il manque précisément la colonne "Doctor".

    def test_detects_duplicates(self, sample_df):
        df = pd.concat([sample_df, sample_df.iloc[[0]]], ignore_index=True) #on créé 2 lignes doublons dans le dataset
        result = run_quality_checks(df, EXPECTED_COLUMNS)
        assert result["checks"]["duplicate_rows"] == 1 #On s'attend à détecter exactement 1 ligne en doublon.

    def test_detects_invalid_age(self, sample_df):
        sample_df.loc[0, "Age"] = 200 #test age irréaliste
        result = run_quality_checks(df, EXPECTED_COLUMNS)
        assert result["passed"] is False
        assert result["checks"]["invalid_ages"] == 1 

class TestDataframeToDocuments:

    def test_conversion_preserves_row_count(self, sample_df):
        df = sample_df.copy() # pour faciliter l'ecriture des conversions
        df["Date of Admission"] = pd.to_datetime(df["Date of Admission"])
        df["Discharge Date"] = pd.to_datetime(df["Discharge Date"]) # Conversion en datetime, car dans sample_df sont en simples chaînes
        docs = dataframe_to_documents(df)
        assert len(docs) == len(df)
        # Vérifie qu'on obtient bien 1 document Mongo par ligne du dataFrame (aucune ligne perdue ni dupliquée pendant la conversion)

    def test_conversion_nested_admission_field(self, sample_df):
        df = sample_df.copy() # pour faciliter l'ecriture des conversions
        df["Date of Admission"] = pd.to_datetime(df["Date of Admission"])
        df["Discharge Date"] = pd.to_datetime(df["Discharge Date"])
        docs = dataframe_to_documents(df)
        assert "admission" in docs[0]
        assert docs[0]["admission"]["room_number"] == 101
        assert docs[0]["admission"]["type"] == "Urgent"
        #vérifie spécifiquement la structure imbriquée : le premier document doit avoir une clé "admission" contenant elle-même "room_number" et "type" avec les bonnes valeurs issues de la première ligne du DataFrame.

    def test_conversion_types(self, sample_df):
        df = sample_df.copy() # pour faciliter l'ecriture des conversions
        df["Date of Admission"] = pd.to_datetime(df["Date of Admission"])
        df["Discharge Date"] = pd.to_datetime(df["Discharge Date"])
        docs = dataframe_to_documents(df)
        assert isinstance(docs[0]["age"], int)
        assert isinstance(docs[0]["billing_amount"], float)
        # Vérifie que les conversions de type (int/float dans dataframe_to_documents) fonctionnent bien


class TestCompareBeforeAfter:

    def test_counts_match(self, sample_df):
        mock_collection = MagicMock() # Crée un objet factice qui va se comporter comme une collection pymongo
        mock_collection.count_documents.return_value = len(sample_df) # vérification du nombre de lignes entre la collection et le df
        mock_collection.find_one.return_value = {
            "name": "John Doe", "age": 45, "gender": "Male", "blood_type": "A+",
            "medical_condition": "Diabetes",
            "admission": {"date": None, "type": "Urgent", "room_number": 101},
            "discharge_date": None, "doctor": "Dr. Alice", "hospital": "General Hospital",
            "insurance_provider": "Aetna", "billing_amount": 1000.50,
            "medication": "Metformin", "test_results": "Normal",
        }
        # document type que l'on doit retrouver
        result = compare_before_after(sample_df, mock_collection) #fonction pour comparer la collection et le df exemple
        assert result["passed"] is True
        assert result["checks"]["counts_match"] is True

    def test_counts_mismatch_fails(self, sample_df):
        mock_collection = MagicMock()
        mock_collection.count_documents.return_value = len(sample_df) - 1 # Cette fois on simule volontairement un décalage : un document de moins côté Mongo que côté source
        mock_collection.find_one.return_value = {} # Échantillon vide simulé également.
        result = compare_before_after(sample_df, mock_collection)
        assert result["passed"] is False
        assert result["checks"]["counts_match"] is False
        #on vérifie que la fonction détecte bien ce problème et fait échouer le contrôle, ce qui est lecomportement attendu en cas d'anomalie.


class TestLoadAndCleanCsv: #test avec la lecture d'un fichier csv

    def test_load_and_clean(self, tmp_path, sample_df):
        csv_path = tmp_path / "sample.csv"
        df = sample_df.copy()
        df.loc[0, "Name"] = "jOhN dOe"
        df.to_csv(csv_path, index=False) #ecriture dans le fichier csv temp
        cleaned = load_and_clean_csv(str(csv_path)) #renomme correctement
        assert cleaned.loc[0, "Name"] == "John Doe" #vérifie que "jOhN dOe" a bien été normalisé en "John Doe".
        assert pd.api.types.is_integer_dtype(cleaned["Age"])
        assert pd.api.types.is_float_dtype(cleaned["Billing Amount"])#vérifie que le typage forcé après le chargement + nettoyage.

    def test_raises_on_missing_columns(self, tmp_path, sample_df):
        csv_path = tmp_path / "bad.csv"
        sample_df.drop(columns=["Doctor"]).to_csv(csv_path, index=False) #retrait d'une colonne
        with pytest.raises(ValueError):
            load_and_clean_csv(str(csv_path)) #fonction load_and_clean_csv contient une règle de sécurité si des colonnes manquent dans le CSV.
            #si il y a bien l'erreur, le test est validé