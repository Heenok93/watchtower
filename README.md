![Python](https://img.shields.io/badge/Python-3.11-blue)
![SQLite](https://img.shields.io/badge/SQLite-Database-blue)
![License](https://img.shields.io/badge/license-MIT-orange.svg?style=flat)
![GitHub last commit](https://img.shields.io/github/last-commit/Heenok93/belote-cards-vision)

# Watchtower

Watchtower est un système léger de veille scientifique automatisée. Il collecte des articles, applique des profils thématiques déterministes, puis classe les articles uniques avec deux étages locaux :

- **System 1 — JEV 0.8 V3** : classification multilabel initiale, une exécution par article ;
- **System 2 — LFM2.5 Instruct** : seconde lecture locale des seuls articles dont certaines dimensions se situent dans les bandes d'incertitude ;
- **Consolidation** : application des règles de routage, arbitrage System 2, conservation des décisions humaines et historique versionné.

La taxonomie comprend huit dimensions indépendantes. Les labels ne forment pas une hiérarchie primaire/secondaire.

## Pipeline de production

```text
run_collect.py
    ↓
run_filter.py
    ↓
build_classification_queue.py
    ↓
run_llm.py                    # System 1 — JEV08
    ↓
build_system2_queue.py        # routage par dimension, dédoublonné par article
    ↓
run_system2.py                # System 2 — LFM2.5, reprise par lots
    ↓
processing/consolidation.py   # article_classifications + history
    ↓
generate_digest.py + export_classifications.py
```

`main.py` orchestre ces étapes. Les scripts individuels restent exécutables séparément. `run_llm.py` conserve son nom pour la compatibilité ; il correspond bien à **System 1**.

## Taxonomie

- `ai_relevant`
- `health_relevant`
- `agentic_ai_health`
- `digital_health_ai`
- `clinical_medicine_ai`
- `laboratory_ai`
- `epidemics_public_health_ai`
- `drug_development_ai`

Les dimensions sont évaluées indépendamment et peuvent se chevaucher. Le périmètre santé est humain. Les définitions opérationnelles détaillées sont intégrées dans les prompts System 1 et System 2.

## Modèles et routage

Valeurs par défaut :

| Étape | Modèle | Configuration |
|---|---|---|
| System 1 | `jev08:latest` | `WATCHTOWER_SYSTEM1_MODEL` |
| System 2 | `tomng/lfm2.5-instruct:latest` | `WATCHTOWER_SYSTEM2_MODEL` |
| Ollama | `http://localhost:11434` | `WATCHTOWER_SYSTEM2_HOST` |

System 2 utilise le prompt **V2** (`lfm25_multilabel_review_v2_2026-11-06`). Le prompt V3 reste un artefact d'évaluation et n'est pas utilisé en production.

Les seuils de routage opérationnels sont figés dans `processing/system2_routing.py` :

| Dimension | Borne basse | Borne haute |
|---|---:|---:|
| AI relevant | 0.422 | 0.422 |
| Health relevant | 0.543 | 0.543 |
| Agentic AI in Health | 0.500 | 0.560 |
| Digital Health AI | 0.540 | 0.665 |
| Clinical Medicine AI | 0.402 | 0.402 |
| Laboratory AI | 0.489 | 0.489 |
| Epidemics / Public Health AI | 0.732 | 0.732 |
| Drug Development AI | 0.800 | 0.860 |

Quand les bornes sont égales, System 1 décide directement. Pour une bande non nulle, `[low, high)` est envoyé à System 2 ; au-dessus ou égal à `high`, la décision System 1 est positive. Les seuils sont des **cutoffs opérationnels exploratoires**, pas des probabilités calibrées ni des estimations statistiques définitives.

System 2 renvoie huit booléens. Les valeurs 0/1 stockées dans `scores_json` pour cette prédiction sont des codes de décision, **pas des probabilités**. Les scores continus System 1 sont conservés dans la classification consolidée.

## Installation

Python 3.11+ recommandé.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -r requirements.txt
```

Copier `.env.example` vers `.env` et ajuster les variables si nécessaire. Les valeurs par défaut fonctionnent si Ollama écoute sur `localhost:11434` et si les deux modèles sont installés.

```bash
ollama pull jev08:latest
ollama pull tomng/lfm2.5-instruct:latest
```

La base SQLite est créée automatiquement dans `storage/watchtower.db`. Les migrations 008 à 011 créent les tables de prédictions, de classification courante, d'historique et les métadonnées de file System 2. Les migrations sont idempotentes.

## Commandes

### Pipeline complet

```bash
python main.py
```

Par défaut, `main.py` traite au maximum **10 articles System 2** par exécution. Les autres restent dans la file et seront repris au prochain lancement.

```bash
# Limiter System 1
python main.py --llm-limit 20

# Traiter un lot System 2 différent
python main.py --system2-limit 5

# Laisser System 2 en attente, consolider les articles qui n'en ont pas besoin
python main.py --skip-system2

# Sauter la collecte RSS et travailler sur les articles déjà en base
python main.py --skip-collect

# Reprendre System 2 sur les articles en base, sans collecte ni System 1
python main.py --skip-collect --skip-system1 --system2-limit 10 --skip-digest

# Réutiliser les résultats persistés de classification sans relancer System 1
python main.py --skip-system1

# Ne pas produire les sorties
python main.py --skip-digest

# Réinitialiser la base après sauvegarde
python main.py --fresh
```

`--skip-collect` saute uniquement la collecte RSS : le filtre déterministe et la reconstruction de la file continuent sur les articles déjà stockés en base. `--skip-system1` (alias historique `--skip-llm`) actualise la file, réutilise les prédictions System 1 existantes encore valides, puis peut poursuivre le routage et System 2. `--skip-system2` laisse les articles routés en attente. Les articles qui n'ont pas encore de prédiction System 1 ne sont jamais consolidés prématurément.

### Étapes autonomes

```bash
python run_collect.py
python run_filter.py
python build_classification_queue.py
python run_llm.py --limit 10
python build_system2_queue.py --dry-run
python build_system2_queue.py
python run_system2.py --limit 10
python -m processing.consolidation --allow-pending-system2
python generate_digest.py
python export_classifications.py
```

`run_system2.py` est volontairement conservé comme étape autonome et reprenable. Une interruption ne supprime pas les prédictions déjà persistées. Relancer la commande reprend les articles restants.

### Adjudication humaine

Une décision humaine modifie uniquement la classification consolidée, jamais les prédictions brutes. Elle conserve les huit scores System 1, les sept autres labels, les identifiants de prédiction et ajoute une entrée d'ajustement ainsi qu'une nouvelle révision dans `article_classification_history`.

```bash
python adjudicate_article.py \
  --article-id 123 \
  --dimension digital_health_ai \
  --decision true \
  --reason "Le système est un outil numérique de soins intégré au parcours patient." \
  --reviewer "initiales"
```

Valeurs de `--decision` : `true`, `false`, `needs_review`. `needs_review` conserve le label provisoire et place l'article dans la section de revue du digest. Une adjudication ultérieure `true` ou `false` peut le résoudre.

## Données et traçabilité

| Table | Rôle |
|---|---|
| `articles` | Articles collectés et métadonnées |
| `article_topic_results` | Résultats du filtre par profil |
| `classification_queue` | Une ligne par article unique, provenance des profils, statut et routage |
| `model_predictions` | Prédictions brutes immuables System 1 / System 2 |
| `article_classifications` | Classification consolidée courante, une ligne par article |
| `article_classification_history` | Historique append-only des révisions |
| `llm_classification_audit` | Audit historique du pipeline LLM initial |

Statuts de file : `pending`, `system1_done`, `system2_pending`, `completed`, `error`, `obsolete`. `needs_review` est un statut de classification consolidée, pas un état de file.

## Sorties

Chaque exécution `main.py` crée un dossier horodaté dans `outputs/` avec :

- `watchtower_digest.md` : candidats finaux, puis articles `needs_review`, puis articles encore en attente ;
- `watchtower_classifications.csv` : une ligne par article consolidé, huit labels, huit scores System 1, statut, révision et provenance.

Le digest ne présente pas les articles `needs_review` comme des candidats finaux. Le CSV produit par `main.py` inclut les lignes `needs_review` pour faciliter la revue ; `python export_classifications.py` n'exporte que les classifications finales par défaut. Ajouter `--include-needs-review` pour les inclure.

## Tests

```bash
python -m pytest -q
```

Les tests couvrent les fonctions existantes, le routage System 2, le contrat strict du prompt V2, la consolidation, l'idempotence et l'upsert d'adjudication humaine.

## Limites

- Les scores System 1 sont des scores de décision du modèle, pas des probabilités calibrées.
- Les labels System 2 sont catégoriels et ne sont pas des probabilités.
- Les cutoffs ont été choisis comme compromis opérationnel sur un benchmark stratifié limité ; ils doivent être réévalués si la taxonomie, le prompt ou le modèle change.
- La classification reste une aide au tri bibliographique. La validation scientifique et la vérification des articles demeurent humaines.
- Watchtower n'est ni une revue systématique exhaustive ni un système d'aide à la décision clinique.
