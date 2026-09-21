// init-mongo.js
// Exécuté automatiquement par l'image MongoDB au premier démarrage
// du conteneur (dossier /docker-entrypoint-initdb.d/), UNIQUEMENT si le volume
// de données est vide.
//
// Objectif : créer la base "healthcare_db" et deux utilisateurs applicatifs
// avec des rôles distincts, conformément au principe de moindre privilège.

db = db.getSiblingDB("healthcare_db");

// 1) Utilisateur "migration_user" : role readWrite, utilisé par le script de
//    migration Python pour écrire/mettre à jour les documents et créer les index.
db.createUser({
  user: "migration_user",
  pwd: "Ctressecurise123",
  roles: [
    { role: "readWrite", db: "healthcare_db" },
  ],
});

// 2) Utilisateur "analyst_user" : role read seul, destiné aux outils de
//    reporting / BI du client qui ne doivent jamais pouvoir modifier les données.
db.createUser({
  user: "analyst_user",
  pwd: "changeme_readonly",
  roles: [
    { role: "read", db: "healthcare_db" },
  ],
});

// 3) Création anticipée de la collection "patients" (facultatif, le script
//    Python la crée aussi implicitement lors du premier insert).
db.createCollection("patients");

print("Initialisation MongoDB terminée : base 'healthcare_db', utilisateurs 'migration_user' (readWrite) et 'analyst_user' (read) créés.");