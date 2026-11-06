# Watchtower — final integration bundle

Version de finalisation : 2026-11-06.

## Changements intégrés

- `main.py` orchestre désormais collecte, filtre, file article-level, System 1, routage System 2, System 2, consolidation et exports.
- `run_llm.py` reste le point d'entrée System 1 JEV08 pour préserver la compatibilité.
- `run_system2.py` reste un script autonome, reprenable et limité par lot ; la valeur par défaut de `main.py` est 10 articles par exécution.
- Le prompt System 2 V2 est celui utilisé par `processing/system2_classifier.py`, avec le modèle `tomng/lfm2.5-instruct:latest`.
- `processing/consolidation.py` arbitre les dimensions routées, conserve les scores continus System 1 et ne réécrit jamais les prédictions brutes.
- `adjudicate_article.py` applique une adjudication humaine via UPSERT SQL transactionnel et ajoute une révision à l'historique.
- `generate_digest.py` lit la classification consolidée et sépare les candidats finaux, les cas `needs_review` et les articles encore en attente.
- `export_classifications.py` produit un CSV article-level : huit labels, huit scores System 1 et métadonnées de provenance.
- Les changements d'input, de taxonomie ou de prompt System 1 invalident l'ancienne classification consolidée en la marquant `stale`, avec conservation de l'historique.
- La migration 011 est incluse dans `storage/migration_runner.py`.
- `.env.example` documente les variables de modèles locaux.
- Tests d'intégration ajoutés pour consolidation, adjudication, digest et export.

## Démarrage

1. Décompresser ce bundle dans un nouveau dossier de travail.
2. Installer les dépendances : `pip install -r requirements.txt`.
3. Copier `.env.example` vers `.env` si des paramètres locaux doivent être modifiés.
4. Vérifier Ollama et les modèles configurés.
5. Exécuter `python main.py --system2-limit 10`.

La base SQLite locale n'est volontairement pas incluse dans l'archive : le fichier `storage/watchtower.db` est une donnée locale, ignorée par Git. La base déjà présente dans votre dossier de travail n'a pas été modifiée par cette préparation. Au premier démarrage, `init_database()` applique les migrations manquantes.

## Adjudication manuelle

```bash
python adjudicate_article.py --article-id 123 --dimension digital_health_ai --decision true --reason "Justification de la décision" --reviewer "initiales"
```

Décisions autorisées : `true`, `false`, `needs_review`.

## Validation effectuée

- Compilation Python : succès.
- `pytest -q` : **41 tests passés**.
- Aucune exécution réelle Ollama, collecte RSS ou écriture dans la base de production n'a été lancée pendant la préparation du bundle.

## Remarque sur les artefacts d'évaluation

Les scripts, CSV, prompts et rapports d'évaluation fournis dans le ZIP source ont été conservés. Ils ne sont pas utilisés automatiquement par le pipeline de production, qui utilise le prompt System 2 V2 et les seuils de `processing/system2_routing.py`.
