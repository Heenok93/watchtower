![Python](https://img.shields.io/badge/Python-3.11-blue)
![SQLite](https://img.shields.io/badge/SQLite-Database-blue)
![License](https://img.shields.io/badge/license-MIT-orange.svg?style=flat)
![GitHub last commit](https://img.shields.io/github/last-commit/Heenok93/watchtower)

# 🔭 Watchtower

Watchtower est un système léger de veille scientifique automatisée.

Il collecte des publications depuis plusieurs flux RSS, normalise leurs métadonnées, élimine les doublons, applique des profils thématiques configurés en YAML, puis utilise facultativement un modèle de langage local pour examiner les cas ambigus.

Le résultat final est un digest scientifique en Markdown indiquant clairement l’origine de chaque sélection :

- candidat retenu par le filtre déterministe ;
- article retenu après examen par le LLM ;
- article encore en attente d’examen ;
- article exclu après examen par le LLM.

Watchtower est conçu comme un outil de veille légère et récurrente. Il n’a pas vocation à remplacer une recherche bibliographique exhaustive ni une revue systématique.

---

# 🧭 Objectifs

Le MVP couvre les fonctions suivantes :

- collecte depuis plusieurs flux RSS ;
- normalisation des articles ;
- déduplication par DOI, PMID, URL source ou empreinte ;
- stockage dans une base SQLite ;
- filtrage déterministe par profils thématiques YAML ;
- classement en trois catégories :
  - `candidate` ;
  - `llm_review` ;
  - `reject` ;
- examen facultatif des cas ambigus par un LLM local via Ollama ;
- enrichissement léger des métadonnées lorsque le résumé est insuffisant ;
- persistance des décisions et de leur contexte ;
- génération d’un digest Markdown ;
- audit des appels LLM ;
- reprise possible après interruption du traitement LLM.

Le filtre déterministe constitue le premier étage principal. Le LLM intervient uniquement sur une petite frontière de cas ambigus.

---

# 🏗️ Architecture générale

```text
Flux RSS
   │
   ▼
run_collect.py
   │
   ├── normalisation
   ├── déduplication
   └── stockage SQLite
   │
   ▼
run_filter.py
   │
   ├── chargement des profils YAML
   ├── filtrage déterministe
   └── candidate / llm_review / reject
   │
   ▼
run_llm.py
   │
   ├── contrôle de la qualité du résumé
   ├── enrichissement léger si nécessaire
   ├── classification structurée via Ollama
   └── audit et persistance
   │
   ▼
generate_digest.py
   │
   ├── candidats déterministes
   ├── articles retenus par le LLM
   ├── cas en attente
   └── exclusions LLM
   │
   ▼
Digest Markdown
```

---

# 📁 Organisation du projet

watchtower/
├── collectors/
│   └── rss_collector.py
├── config/
│   ├── feeds.yaml
│   └── topics/
│       ├── agentic_epidemiology.yaml
│       └── automated_reviews.yaml
├── enrichment/
│   └── enrichment_service.py
├── models/
│   ├── schemas.py
│   └── llm_results.py
├── processing/
│   ├── abstract_quality.py
│   ├── llm_classifier.py
│   └── llm_run_support.py
├── providers/
│   └── ollama_provider.py
├── storage/
│   ├── database.py
│   ├── repositories.py
│   ├── topic_result_repository.py
│   ├── llm_audit_repository.py
│   └── watchtower.db
├── tests/
├── benchmarks/
├── run_collect.py
├── run_filter.py
├── run_llm.py
├── generate_digest.py
└── README.md

---

# ⚙️ Installation

Prérequis
Python ;
Git ;
uv recommandé pour la gestion de l’environnement ;
Ollama pour la classification locale facultative.

Le projet a été développé et testé sous Windows avec Git Bash.

Cloner le dépôt
Shell
git clone <URL_DU_DEPOT>
cd watchtower
Installer les dépendances

Si le projet contient un pyproject.toml et un fichier de verrouillage :

Shell
uv sync

Pour exécuter les commandes dans l’environnement géré par uv :

Shell
uv run python run_collect.py

Il est également possible d’activer l’environnement virtuel puis d’utiliser directement python.

Vérifier l’installation
Shell
python -m py_compile run_collect.py
python -m py_compile run_filter.py
python -m py_compile run_llm.py
python -m py_compile generate_digest.py

---

# 🤖 Configuration d’Ollama

Watchtower utilise actuellement le modèle configuré dans run_llm.py :

Python
MODEL = "qwen3-light:latest"
TEMPERATURE = 0.0

Vérifier qu’Ollama fonctionne :

Shell
ollama list

Puis vérifier l’accès depuis Python :

Shell
python -c "import ollama; print(ollama)"

Le modèle doit être présent dans la liste des modèles installés ou remplacé par un modèle disponible localement.

La couche OllamaProvider isole le fournisseur du reste de l’application. Un autre modèle ou fournisseur pourra donc être testé ultérieurement sans modifier toute la chaîne de traitement.

---

# 📰 Configuration des sources

Les sources RSS sont déclarées dans :

config/feeds.yaml

Chaque source peut notamment préciser :

son identifiant ;
son nom ;
son URL RSS ;
son type de contenu ;
son journal ou fournisseur ;
son statut actif ou inactif.

Exemple indicatif :

```text
sources:
id: nature_general

name: Nature
url: "URL_DU_FLUX"
enabled: true
content_type: mixed
journal: Nature
```

Le MVP a été validé avec plusieurs types de sources :

revues scientifiques ;
prépublications ;
blogs de recherche ;
sources généralistes ou spécialisées.

---

# 🎯 Configuration des topics

Les profils thématiques sont définis dans :

Plain Text
config/topics/

Chaque profil YAML décrit notamment :

l’identifiant du topic ;
son nom ;
sa description scientifique ;
les termes d’inclusion ;
les termes de contexte ;
les termes d’exclusion ;
les termes prioritaires ;
les groupes conceptuels requis ;
les groupes secondaires ;
les poids de scoring ;
les seuils de décision.

Exemple simplifié :

```yaml
id: example_topic
name: Example Scientific Topic
 
description: >
Description précise du périmètre scientifique surveillé.
 
required_groups:
method:
terms:
- artificial intelligence
- machine learning
- large language model
 
application:
terms:
- epidemiology
- public health
- disease surveillance
 
thresholds:
reject_below: 2
llm_review_below: 6
```

Les groupes requis servent à vérifier que plusieurs concepts apparaissent dans l’article. La classification LLM examine ensuite si ces concepts entretiennent réellement la relation scientifique attendue.

La description doit être suffisamment précise pour indiquer :

ce qui entre dans le périmètre ;
la relation attendue entre les concepts ;
ce qui ne suffit pas à établir la pertinence.

---

# 🚀 Utilisation

Les commandes suivantes doivent être exécutées depuis la racine du projet.

1. Collecter les articles

```Shell
python run_collect.py
```

Cette étape :

interroge les sources RSS actives ;
normalise les articles ;
recherche les doublons ;
insère uniquement les nouveaux articles ;
enregistre un audit dans processing_runs.

La déduplication peut reposer sur :

DOI ;
PMID ;
URL source normalisée ;
empreinte calculée sur les métadonnées disponibles.

Il est normal que plusieurs éléments d’un flux soient ignorés lorsqu’ils désignent le même article.

2. Appliquer les filtres déterministes

```Shell
python run_filter.py
```

Chaque article est évalué contre chaque profil actif.

Les résultats sont enregistrés dans article_topic_results.

Les décisions possibles sont :

candidate : correspondance déterministe suffisamment forte ;
llm_review : cas intermédiaire nécessitant un examen sémantique ;
reject : correspondance insuffisante ;
error : erreur de traitement.

Le filtre peut être relancé. La persistance utilise un comportement de mise à jour adapté aux couples article/topic existants.

3. Examiner les cas ambigus avec le LLM

```Shell
python run_llm.py
```

Cette étape ne traite que les lignes llm_review qui ne possèdent pas encore de résultat LLM exploitable.

Pour chaque couple article/topic :

la qualité du titre et du résumé est évaluée ;
un enrichissement léger peut être tenté si le résumé est insuffisant ;
le titre, le résumé et le profil thématique sont fournis au modèle ;
la réponse est validée avec le modèle Pydantic LLMResult ;
le résultat est sauvegardé ;
la tentative est enregistrée dans l’audit LLM.

Le traitement peut être interrompu avec Ctrl+C. Les articles terminés avant l’interruption restent enregistrés et les autres restent en attente.

4. Générer le digest

```Shell
python generate_digest.py
```

Le digest distingue explicitement :

les candidats du filtre déterministe ;
les articles retenus par le LLM ;
les articles rejetés par le LLM ;
les articles encore en attente d’examen.

Un traitement LLM incomplet n’empêche pas la génération du digest.

Les cas en attente sont signalés et ne sont pas présentés comme validés.

---

# 🗄️ Base de données

La base SQLite se trouve par défaut dans :

```text
storage/watchtower.db
```

Le schéma du MVP contient les tables suivantes :

```text
articles
article_topic_results
processing_runs
llm_classification_audit
```

SQLite peut également créer automatiquement :

```text
sqlite_sequence
articles
```

Contient les articles collectés et leurs métadonnées normalisées.

article_topic_results

Contient le résultat du filtre pour chaque couple article/topic, puis les éventuels résultats de classification LLM.

processing_runs

Conserve les informations relatives aux exécutions de collecte et de traitement.

llm_classification_audit

Conserve les informations nécessaires pour auditer les tentatives LLM, notamment :

identifiant du run ;
article ;
topic ;
fournisseur ;
modèle ;
température ;
version du prompt ;
empreintes des entrées ;
statut ;
résultat éventuel ;
erreur éventuelle.

---

# 🔄 Repartir d’une base vierge

Avant de supprimer la base, créer une sauvegarde :

```Shell
cp storage/watchtower.db storage/watchtower_backup.db
```
Puis supprimer la base active :

```Shell
rm storage/watchtower.db
```

Ne pas créer manuellement un fichier SQLite vide. Utiliser le mécanisme normal d’initialisation du projet afin de vérifier que le schéma complet peut être recréé.

Vérifier ensuite les tables :

```Shell
python -c "from storage.database import get_connection; c=get_connection(); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]); c.close()"
```

Résultat attendu pour le schéma actuel :

```text
[
'article_topic_results',
'articles',
'llm_classification_audit',
'processing_runs',
'sqlite_sequence'
]
```

---

# ✅ Tests

Lancer l’ensemble des tests :

```Shell
python -m unittest discover -s tests -v
```

Exécuter uniquement les tests du patch LLM :

```Shell
python -m unittest discover -s tests -p "test_llm_patch.py" -v
```

Les tests couvrent notamment :

l’utilisation des prompts réels ;
la validation du résultat structuré ;
l’absence d’enrichissement pour un résumé déjà exploitable ;
l’amélioration ou la dégradation de la qualité d’un résumé ;
le rejet d’un enrichissement dégradé ;
la poursuite du traitement après une erreur d’enrichissement ;
l’audit d’une erreur du fournisseur ;
l’idempotence de la migration d’audit.

---

# 📊 Validation du MVP

Le pipeline a été testé depuis une base vierge avec :

7 sources RSS actives ;
1 001 entrées trouvées ;
1 000 articles uniques insérés ;
0 erreur de collecte ;
2 profils thématiques ;
2 000 couples article/topic persistés ;
10 couples seulement orientés vers le LLM.

Un second passage de collecte sur la même base a donné :

1 001 entrées retrouvées ;
0 nouvelle insertion ;
1 001 doublons ignorés ;
0 erreur ;
toujours 1 000 articles dans la base.

Ce test valide le comportement de déduplication sur les sources utilisées.

Le digest a également été généré après interruption volontaire de run_llm.py. Les décisions déjà terminées ont été conservées et les cas non traités ont été correctement présentés comme étant en attente.

---

# ⚠️ Limites connues
Classification LLM locale

Le modèle local actuellement utilisé est un modèle Qwen fortement quantifié, exécuté sur une machine sans GPU dédié.

Les conséquences observées sont :

temps de traitement relativement long ;
faux positifs possibles ;
tendance à inventer une relation entre l’article et le topic attendu ;
confiance souvent élevée même lorsque la justification est incorrecte ;
faible valeur de la confiance comme mesure calibrée.

Le LLM doit donc être considéré comme un filtre secondaire expérimental.

Une décision relevant=true signifie :

le modèle estime l’article pertinent selon les informations fournies.

Elle ne signifie pas :

la pertinence scientifique a été vérifiée avec certitude.

Le digest rappelle explicitement que la pertinence doit être vérifiée et que la confiance du modèle n’est pas une garantie.

Candidats déterministes

Un candidat déterministe correspond à une association lexicale forte.

Cette décision n’est pas une validation sémantique. Certains articles peuvent contenir les bons termes sans répondre exactement au périmètre scientifique recherché.

Sources RSS

Les résultats dépendent :

du contenu exposé par chaque flux ;
de la stabilité des URLs ;
de la présence d’un DOI ou d’autres identifiants ;
de la qualité et de la longueur des résumés ;
de la fréquence de mise à jour des flux.

Watchtower n’a pas vocation à garantir une couverture bibliographique exhaustive.

Enrichissement

L’enrichissement OpenAlex/Crossref est volontairement léger.

Il sert à améliorer des métadonnées insuffisantes, mais ne constitue pas une stratégie de récupération exhaustive du texte intégral.

---

# 🧪 Benchmarks LLM

Le dossier benchmarks/ peut contenir des jeux figés de couples article/topic.

Ces jeux permettent de comparer :

plusieurs prompts ;
plusieurs modèles locaux ;
plusieurs niveaux de quantification ;
de futurs fournisseurs cloud ;
de futurs environnements GPU.

Les entrées figées ne doivent pas être modifiées pendant une comparaison.

Les fichiers de benchmark peuvent notamment conserver :

les articles ;
les profils thématiques ;
l’empreinte des entrées ;
les prompts réellement envoyés ;
les décisions ;
les justifications ;
les erreurs techniques ;
les annotations manuelles.

La comparaison d’un nouveau modèle doit utiliser exactement les mêmes entrées afin d’éviter de confondre un changement de modèle avec un changement de données ou de profil.

# 🧹 Fichiers à ignorer dans Git

Le .gitignore devrait au minimum exclure les éléments locaux ou générés :

```python
.ignore
# Python
__pycache__/
*.py[cod]
.pytest_cache/
 
# Environnements
.venv/
venv/
 
# Base SQLite locale
storage/watchtower.db
storage/*.db-wal
storage/*.db-shm
 
# Sauvegardes locales
storage/*_backup.db
storage/*_before_*.db
 
# Sorties générées
digests/
output/
outputs/
 
# IDE
.vscode/
.idea/
 
# Système
.DS_Store
Thumbs.db
```

Les jeux de benchmark destinés à la régression peuvent être versionnés s’ils ne contiennent pas de données confidentielles ou soumises à restriction.

---

# 🛠️ Résolution de problèmes

Ollama ne répond pas

Vérifier qu’Ollama est démarré :

```Shell
ollama list
```

Vérifier ensuite l’import Python :

```Shell
python -c "import ollama; print(ollama)"
Le modèle configuré est absent
```

Afficher les modèles installés :

```Shell
ollama list
```

Puis modifier la constante MODEL dans run_llm.py ou installer le modèle attendu.

run_llm.py est trop lent

Le traitement peut être interrompu avec :

```Plain Text
Ctrl+C
```

Les classifications déjà persistées restent disponibles. Le digest peut être généré avec les résultats partiels.

La base SQLite reste verrouillée dans les tests

Lorsqu’une fonction ouvre elle-même une connexion, elle doit également la fermer.

Exemple :

```Python
from contextlib import closing
 
with closing(get_connection()) as connection:
with connection:
connection.execute(...)
```

Le gestionnaire de contexte SQLite gère la transaction, mais la fermeture explicite de la connexion reste nécessaire.

Aucun article n’est envoyé au LLM

Vérifier les résultats du filtre :

```Shell
python run_filter.py
```

Le nombre de lignes LLM review doit être supérieur à zéro pour que run_llm.py ait quelque chose à traiter.

Le digest contient des articles en attente

C’est un comportement normal lorsque run_llm.py a été interrompu ou lorsque certaines classifications ont échoué.

Ces articles sont présentés dans une section séparée et ne sont pas considérés comme validés.

---

# 🗺️ Périmètre du MVP

Watchtower reste volontairement léger.

Le MVP comprend :

collecte RSS ;
normalisation ;
déduplication ;
stockage SQLite ;
profils YAML ;
filtre déterministe ;
classification LLM facultative ;
enrichissement léger ;
audit ;
digest.

Les fonctions suivantes ne font pas partie du MVP Watchtower :

recherche bibliographique exhaustive ;
recherche multi-sources à la demande ;
interrogation approfondie d’un corpus ;
PaperQA2 ;
retrieval vectoriel ;
analyse du texte intégral ;
workflows agentiques complexes ;
base vectorielle ;
orchestration de modèles lourds ;
accès systématique à Scopus, Mendeley ou d’autres APIs bibliographiques.

Ces fonctions relèvent du projet séparé Research Workbench.

---

# 🔮 Évolutions possibles

Évolutions raisonnables sans modifier l’architecture générale :

tester quelques modèles locaux ou cloud sur les benchmarks figés ;
ajouter de nouvelles sources RSS ;
créer de nouveaux profils YAML ;
améliorer la présentation du digest ;
planifier l’exécution du pipeline ;
envoyer automatiquement le digest par e-mail ;
ajouter une commande unique orchestrant les quatre étapes ;
ajouter une politique explicite de reprise des appels LLM en erreur.

Les modèles plus lourds, les APIs bibliographiques avancées et les traitements GPU distants seront étudiés séparément dans Research Workbench.

---

# 📝 Commandes principales

Pipeline complet :

```Shell
python run_collect.py
python run_filter.py
python run_llm.py
python generate_digest.py
```
Tests :

```Shell
python -m unittest discover -s tests -v
```
Vérification des tables :

Shell
```python -c "from storage.database import get_connection; c=get_connection(); print([r[0] for r in c.execute(\"SELECT name FROM sqlite_master WHERE type='table' ORDER BY name\").fetchall()]); c.close()"
```
Vérification d’Ollama :

```Shell
ollama list
```
---

# 📄 Statut

Watchtower MVP : fonctionnel.

Le pipeline principal a été validé depuis une base vierge, y compris :

la collecte multi-source ;
la déduplication ;
le filtrage de plusieurs topics ;
la persistance des résultats ;
la classification LLM partielle ;
l’interruption du traitement LLM ;
la génération d’un digest avec traitements en attente ;
le second passage de collecte sans duplication.

La principale limitation actuelle est la qualité du modèle local fortement quantifié. Cette limitation est isolée derrière une interface fournisseur et pourra être réévaluée ultérieurement avec d’autres modèles.