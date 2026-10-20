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