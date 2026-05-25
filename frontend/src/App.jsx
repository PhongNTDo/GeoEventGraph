import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import graphData from "../../data/graph/graph.json";
import { TYPE_COLORS } from "./graphStyle";

const MapView = lazy(() => import("./MapView").then((module) => ({ default: module.MapView })));
const TopologyView = lazy(() =>
  import("./TopologyView").then((module) => ({ default: module.TopologyView })),
);

const COUNTRY_CENTROIDS = {
  "NationState:iran": [32.4279, 53.688],
  "NationState:united-states": [38.9072, -77.0369],
  "NationState:israel": [31.0461, 34.8516],
  "NationState:pakistan": [30.3753, 69.3451],
  "NationState:lebanon": [33.8547, 35.8623],
  "NationState:iraq": [33.2232, 43.6793],
  "NationState:china": [35.8617, 104.1954],
  "NationState:united-kingdom": [55.3781, -3.436],
  "NationState:united-arab-emirates": [23.4241, 53.8478],
  "NationState:saudi-arabia": [23.8859, 45.0792],
  "NationState:sri-lanka": [7.2945434, 80.5820067],
  "NationState:north-korea": [39.0291092,125.6597108],
  "NationState:afghanistan": [33.9391, 67.7100],
  "NationState:thailand": [13.7245449,100.4682977],
  "NationState:italy": [41.9099533,12.3711893],
  "NationState:turkey": [38.9637, 35.2433],
  "NationState:bahrain": [25.9304, 50.6378],
  "NationState:syria": [34.8021, 38.9968],
  "NationState:russia": [55.5799533,36.7259057],
  "NationState:qatar": [25.3548, 51.1839],
  "NationState:jordan": [30.5852, 36.2384],
  "NationState:Ukraine": [50.4014325, 30.2030549],
};

export function App() {
  const [mode, setMode] = useState("map");
  const [selectedDateIndex, setSelectedDateIndex] = useState(
    graphData.metadata.timeline.available_dates.length - 1,
  );
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [showFlaggedOnly, setShowFlaggedOnly] = useState(false);

  const activeDate = graphData.metadata.timeline.available_dates[selectedDateIndex] ?? null;

  const filteredGraph = useMemo(() => {
    return filterGraph(graphData, activeDate, showFlaggedOnly);
  }, [activeDate, showFlaggedOnly]);

  const selectedEdge = useMemo(
    () => filteredGraph.edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [filteredGraph.edges, selectedEdgeId],
  );

  useEffect(() => {
    if (selectedEdgeId && !filteredGraph.edges.some((edge) => edge.id === selectedEdgeId)) {
      setSelectedEdgeId(null);
    }
  }, [filteredGraph.edges, selectedEdgeId]);

  const statItems = useMemo(
    () => [
      { label: "Visible Nodes", value: filteredGraph.nodes.length },
      { label: "Visible Edges", value: filteredGraph.edges.length },
      { label: "Timeline Date", value: activeDate ?? "N/A" },
      {
        label: "Flagged Locations",
        value: filteredGraph.nodes.filter((node) => node.review_flags.length > 0).length,
      },
    ],
    [filteredGraph, activeDate],
  );

  const nodesById = useMemo(
    () => Object.fromEntries(filteredGraph.nodes.map((node) => [node.id, node])),
    [filteredGraph.nodes],
  );

  return (
    <div className="app-shell">
      <div className="backdrop-grid" />
      <header className="hero">
        <div>
          <p className="eyebrow">Event-Driven Geospatial Knowledge Graph</p>
          <h1>GeoKG Conflict Monitor</h1>
          <p className="lede">
            Explore how military, diplomatic, and blockade relationships evolve across time
            and geography in the extracted corpus.
          </p>
        </div>
        <div className="hero-stats">
          {statItems.map((item) => (
            <article key={item.label} className="stat-card">
              <span>{item.label}</span>
              <strong>{item.value}</strong>
            </article>
          ))}
        </div>
      </header>

      <section className="control-bar">
        <div className="toggle-group">
          <button
            className={mode === "map" ? "toggle active" : "toggle"}
            onClick={() => setMode("map")}
          >
            Map View
          </button>
          <button
            className={mode === "network" ? "toggle active" : "toggle"}
            onClick={() => setMode("network")}
          >
            Topology View
          </button>
        </div>

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showFlaggedOnly}
            onChange={(event) => setShowFlaggedOnly(event.target.checked)}
          />
          Show only flagged geospatial nodes
        </label>
      </section>

      <section className="timeline-card">
        <div className="timeline-labels">
          <div>
            <span className="eyebrow">Timeline Filter</span>
            <strong>{activeDate ?? "No date"}</strong>
          </div>
          <p>
            Scrub the corpus date boundary. Nodes and edges remain visible only if first seen on
            or before the selected date.
          </p>
        </div>
        <input
          className="timeline-slider"
          type="range"
          min="0"
          max={Math.max(graphData.metadata.timeline.available_dates.length - 1, 0)}
          value={selectedDateIndex}
          onChange={(event) => setSelectedDateIndex(Number(event.target.value))}
        />
        <div className="timeline-ticks">
          {graphData.metadata.timeline.available_dates.map((date) => (
            <span key={date}>{date}</span>
          ))}
        </div>
      </section>

      <main className="main-grid">
        <section className="viewport-card">
          <Suspense fallback={<div className="viewport-loading">Loading visualization…</div>}>
            {mode === "map" ? (
              <MapView
                graph={filteredGraph}
                selectedEdgeId={selectedEdgeId}
                onSelectEdge={setSelectedEdgeId}
              />
            ) : (
              <TopologyView
                graph={filteredGraph}
                selectedEdgeId={selectedEdgeId}
                onSelectEdge={setSelectedEdgeId}
              />
            )}
          </Suspense>
        </section>

        <aside className="inspector-card">
          <div className="inspector-header">
            <span className="eyebrow">Evidence Panel</span>
            <h2>{selectedEdge ? selectedEdge.type : "Select an edge"}</h2>
            <p>
              {selectedEdge
                ? `${selectedEdge.source_name} → ${selectedEdge.target_name}`
                : "Click an edge in the map or topology view to inspect article evidence."}
            </p>
          </div>

          {selectedEdge ? (
            <>
              <div className="edge-meta-grid">
                <MetaBlock label="Weight" value={selectedEdge.weight} />
                <MetaBlock label="Articles" value={selectedEdge.article_count} />
                <MetaBlock label="First Seen" value={selectedEdge.first_seen ?? "N/A"} />
                <MetaBlock label="Last Seen" value={selectedEdge.last_seen ?? "N/A"} />
              </div>
              {selectedEdge.review_flags.length > 0 ? (
                <div className="flag-box">
                  {selectedEdge.review_flags.map((flag) => (
                    <p key={`${flag.code}-${flag.message}`}>
                      <strong>{flag.code}</strong>: {flag.message}
                    </p>
                  ))}
                </div>
              ) : null}
              <div className="evidence-list">
                {selectedEdge.evidences.map((evidence, index) => (
                  <article key={`${selectedEdge.id}-${index}`} className="evidence-card">
                    <div className="evidence-meta">
                      <span>{evidence.published_at ?? "Unknown date"}</span>
                      <span>{evidence.source_publication ?? "Unknown source"}</span>
                    </div>
                    <h3>{evidence.title}</h3>
                    <blockquote>{evidence.evidence}</blockquote>
                  </article>
                ))}
              </div>
            </>
          ) : (
            <div className="empty-state">
              <p>Nothing selected yet.</p>
              <p>
                Try the high-weight blockade and negotiation edges first. They are the most
                informative in this dataset.
              </p>
            </div>
          )}
        </aside>
      </main>
    </div>
  );
}

function MetaBlock({ label, value }) {
  return (
    <article className="meta-block">
      <span>{label}</span>
      <strong>{value}</strong>
    </article>
  );
}

function filterGraph(payload, activeDate, showFlaggedOnly) {
  const visibleNodes = payload.nodes.filter((node) => {
    const visibleByDate = !activeDate || !node.first_seen || node.first_seen <= activeDate;
    const visibleByFlag = !showFlaggedOnly || node.review_flags.length > 0;
    return visibleByDate && visibleByFlag;
  });

  const visibleNodeIds = new Set(visibleNodes.map((node) => node.id));
  const visibleEdges = payload.edges
    .filter((edge) => {
      const visibleByDate = !activeDate || edge.first_seen <= activeDate;
      const connected = visibleNodeIds.has(edge.source) && visibleNodeIds.has(edge.target);
      return visibleByDate && connected;
    });

  const mapNodes = deriveMapNodes(visibleNodes, visibleEdges);
  const nodeById = new Map(mapNodes.map((node) => [node.id, node]));
  const enrichedEdges = visibleEdges.map((edge) => ({
    ...edge,
    source_name: nodeById.get(edge.source)?.name ?? edge.source,
    target_name: nodeById.get(edge.target)?.name ?? edge.target,
    source_coords: resolveCoords(nodeById.get(edge.source)),
    target_coords: resolveCoords(nodeById.get(edge.target)),
  }));

  const connectedNodeIds = new Set();
  enrichedEdges.forEach((edge) => {
    connectedNodeIds.add(edge.source);
    connectedNodeIds.add(edge.target);
  });

  return {
    nodes: mapNodes.filter(
      (node) => !showFlaggedOnly || connectedNodeIds.has(node.id) || node.review_flags.length > 0,
    ),
    edges: enrichedEdges,
  };
}

function resolveCoords(node) {
  if (!node) {
    return null;
  }
  const latitude = node.map_latitude ?? node.latitude;
  const longitude = node.map_longitude ?? node.longitude;
  if (latitude == null || longitude == null) {
    return null;
  }
  return [latitude, longitude];
}

function deriveMapNodes(nodes, edges) {
  const nodeMap = new Map(
    nodes.map((node) => [
      node.id,
      {
        ...node,
        map_latitude: node.latitude,
        map_longitude: node.longitude,
        map_position_source:
          node.latitude != null && node.longitude != null ? "geocoded" : null,
      },
    ]),
  );

  for (const [nodeId, coords] of Object.entries(COUNTRY_CENTROIDS)) {
    const node = nodeMap.get(nodeId);
    if (!node || node.map_latitude != null || node.map_longitude != null) {
      continue;
    }
    node.map_latitude = coords[0];
    node.map_longitude = coords[1];
    node.map_position_source = "centroid";
  }

  const adjacency = new Map();
  for (const edge of edges) {
    if (!adjacency.has(edge.source)) adjacency.set(edge.source, []);
    if (!adjacency.has(edge.target)) adjacency.set(edge.target, []);
    adjacency.get(edge.source).push(edge.target);
    adjacency.get(edge.target).push(edge.source);
  }

  for (let pass = 0; pass < 3; pass += 1) {
    for (const node of nodeMap.values()) {
      if (node.map_latitude != null && node.map_longitude != null) {
        continue;
      }
      const neighbors = adjacency.get(node.id) ?? [];
      const anchor = neighbors
        .map((neighborId) => nodeMap.get(neighborId))
        .find((neighbor) => neighbor && neighbor.map_latitude != null && neighbor.map_longitude != null);
      if (!anchor) {
        continue;
      }
      const [latOffset, lngOffset] = deterministicOffset(node.id);
      node.map_latitude = anchor.map_latitude + latOffset;
      node.map_longitude = anchor.map_longitude + lngOffset;
      node.map_position_source = "derived";
    }
  }

  return [...nodeMap.values()];
}

function deterministicOffset(seed) {
  let hash = 0;
  for (let index = 0; index < seed.length; index += 1) {
    hash = (hash * 31 + seed.charCodeAt(index)) >>> 0;
  }
  const angle = (hash % 360) * (Math.PI / 180);
  const radius = 1.8 + ((hash >> 8) % 120) / 100;
  return [Math.sin(angle) * radius, Math.cos(angle) * radius];
}
