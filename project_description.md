# Project Brief: Event-Driven Geospatial Knowledge Graph (GeoKG)

### 1. High-Level Overview
This project bridges the gap between unstructured text, Knowledge Graph (KG) generation, and spatial reasoning. The goal is to build an end-to-end pipeline that ingests a static, curated corpus of news articles and automatically extracts an event-driven, geographically grounded knowledge network. 

To demonstrate this architecture, the initial prototype focuses on a bounded geopolitical dataset: the February–April 2026 Middle East conflict (specifically involving Iran, the US, Israel, and the Strait of Hormuz blockade). The final output is an interactive web dashboard where users can scrub through a timeline to watch diplomatic and military relationships evolve on a global map.

### 2. Core Architecture & Pipeline
The project explicitly avoids automated, daily web-scraping to focus on high-fidelity NLP extraction and UI visualization. The pipeline consists of four distinct stages:

* **Stage 1: Corpus Ingestion:** Processing a curated dataset of 100-200 JSON/CSV formatted news articles containing a date, source, and raw text.
* **Stage 2: LLM-Driven Extraction (Local):** Utilizing a local instruction-tuned LLM (e.g., Llama-3 or Mistral managed via Ollama) to perform zero-shot/few-shot Named Entity Recognition (NER) and Relation Extraction (RE). The model is constrained by a strict system prompt to output a predefined JSON schema, preventing hallucinations of unsupported relationship types.
* **Stage 3: Geocoding & Spatial Validation:** Passing extracted entities (e.g., "Kharg Island") through a geocoding library (like `geopy`/Nominatim) to assign latitude and longitude. A crucial secondary script will flag anomalous coordinates for manual validation to ensure strict spatial accuracy before mapping.
* **Stage 4: Graph Aggregation:** Transforming the JSON output into a `NetworkX` graph. Entities are deduplicated into unique nodes. Repeated relationships between the same entities are collapsed into single, heavily weighted edges that store an array of dates and source-text snippets as evidence.

### 3. Strict Ontology & Schema
To maintain a queryable and visually clean graph, the NLP extraction engine is restricted to the following ontology:

**Allowed Entity Types (Nodes):**
* `NationState` (e.g., Iran, Israel, United States)
* `NonStateActor` (e.g., Hezbollah, Houthi Movement)
* `PoliticalLeader` (e.g., Pezeshkian, Biden)
* `StrategicLocation` (e.g., Strait of Hormuz, Islamabad)
* `MilitaryAsset` (e.g., Naval Fleet, Drone Swarm)

**Allowed Relation Types (Edges):**
* `ATTACKED` (Kinetic military action)
* `THREATENED` (Verbal or diplomatic threats)
* `NEGOTIATED_WITH` (Diplomatic talks, ceasefires)
* `SUPPORTED` (Financial, military, or diplomatic backing)
* `SANCTIONED` (Economic penalties)
* `BLOCKADED` (Naval/movement restrictions)

### 4. Frontend Application (The Visualization Layer)
The output JSON graph will be rendered in a lightweight web application.
* **The Map View:** Utilizing `Leaflet.js` or `Mapbox` to plot nodes spatially. Edges will be styled dynamically based on the relation type (e.g., dashed red for `ATTACKED`).
* **The Topological View:** Utilizing `Cytoscape.js` or `D3.js` to view the network purely by influence, removing geographic constraints.
* **Interactive Controls:** A Time Slider is the primary interactive element, allowing the user to filter nodes and edges by date. Clicking an edge will open a panel displaying the "evidence" (the exact text snippet from the news article).

### 5. Future Academic Expansion (Phase 2)
While Phase 1 is a standalone platform, the architecture acts as a foundational framework for future NLP research. Potential avenues for paper submissions include:
* Evaluating the robustness of LLMs in extracting complex, multi-hop geopolitical relationships.
* Analyzing spatial reasoning errors in LLM outputs when dealing with geographically constrained events (e.g., coordinate-based relative positioning).
* Benchmarking the efficiency of different prompt decomposition strategies on the accuracy of relation extraction.
