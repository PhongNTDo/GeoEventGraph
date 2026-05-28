import { Suspense, lazy, useEffect, useMemo, useState } from "react";
import eventData from "../../data/graph/events.json";
import graphData from "../../data/graph/graph.json";
import { EVENT_COLORS, TYPE_COLORS } from "./graphStyle";

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

const TIMELINE_DATES = [
  ...new Set([
    ...(graphData.metadata.timeline.available_dates ?? []),
    ...(eventData.metadata.timeline.available_dates ?? []),
  ]),
].sort();

const EVENT_TYPES = Object.entries(eventData.metadata.event_type_counts ?? {})
  .sort((left, right) => right[1] - left[1])
  .map(([eventType]) => eventType);

export function App() {
  const [mode, setMode] = useState("map");
  const [selectedDateIndex, setSelectedDateIndex] = useState(TIMELINE_DATES.length - 1);
  const [selectedEdgeId, setSelectedEdgeId] = useState(null);
  const [selectedEventId, setSelectedEventId] = useState(null);
  const [selectedEventType, setSelectedEventType] = useState("all");
  const [minConfidence, setMinConfidence] = useState(0);
  const [showFlaggedOnly, setShowFlaggedOnly] = useState(false);

  const activeDate = TIMELINE_DATES[selectedDateIndex] ?? null;

  const filteredGraph = useMemo(() => {
    return filterGraph(graphData, activeDate, showFlaggedOnly);
  }, [activeDate, showFlaggedOnly]);

  const filteredEvents = useMemo(
    () =>
      filterEvents({
        events: eventData.events,
        activeDate,
        eventType: selectedEventType,
        minConfidence,
        showFlaggedOnly,
      }),
    [activeDate, selectedEventType, minConfidence, showFlaggedOnly],
  );

  const selectedEdge = useMemo(
    () => filteredGraph.edges.find((edge) => edge.id === selectedEdgeId) ?? null,
    [filteredGraph.edges, selectedEdgeId],
  );

  const selectedEvent = useMemo(
    () => filteredEvents.find((event) => event.id === selectedEventId) ?? null,
    [filteredEvents, selectedEventId],
  );

  useEffect(() => {
    if (selectedEdgeId && !filteredGraph.edges.some((edge) => edge.id === selectedEdgeId)) {
      setSelectedEdgeId(null);
    }
  }, [filteredGraph.edges, selectedEdgeId]);

  useEffect(() => {
    if (selectedEventId && !filteredEvents.some((event) => event.id === selectedEventId)) {
      setSelectedEventId(null);
    }
  }, [filteredEvents, selectedEventId]);

  const statItems = useMemo(
    () => [
      { label: "Visible Events", value: filteredEvents.length },
      { label: "Visible Nodes", value: filteredGraph.nodes.length },
      { label: "Visible Edges", value: filteredGraph.edges.length },
      { label: "Timeline Date", value: activeDate ?? "N/A" },
    ],
    [filteredEvents.length, filteredGraph, activeDate],
  );

  return (
    <div className="app-shell">
      <div className="backdrop-grid" />
      <header className="hero">
        <div>
          <p className="eyebrow">Event-Driven Geospatial Knowledge Graph</p>
          <h1>GeoKG Conflict Monitor</h1>
          <p className="lede">
            Explore extracted geopolitical events, compatibility relations, article evidence,
            and geospatial review signals across the corpus timeline.
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
          <button
            className={mode === "events" ? "toggle active" : "toggle"}
            onClick={() => setMode("events")}
          >
            Event View
          </button>
        </div>

        <label className="checkbox-row">
          <input
            type="checkbox"
            checked={showFlaggedOnly}
            onChange={(event) => setShowFlaggedOnly(event.target.checked)}
          />
          Show only flagged records
        </label>
      </section>

      {mode === "events" ? (
        <section className="event-filter-card">
          <label className="filter-field">
            <span>Event type</span>
            <select
              value={selectedEventType}
              onChange={(event) => setSelectedEventType(event.target.value)}
            >
              <option value="all">All event types</option>
              {EVENT_TYPES.map((eventType) => (
                <option key={eventType} value={eventType}>
                  {formatEventType(eventType)} ({eventData.metadata.event_type_counts[eventType]})
                </option>
              ))}
            </select>
          </label>
          <label className="filter-field confidence-field">
            <span>Minimum confidence</span>
            <input
              type="range"
              min="0"
              max="1"
              step="0.05"
              value={minConfidence}
              onChange={(event) => setMinConfidence(Number(event.target.value))}
            />
            <strong>{formatConfidence(minConfidence)}</strong>
          </label>
          <div className="event-type-strip">
            {EVENT_TYPES.map((eventType) => (
              <button
                key={eventType}
                className={selectedEventType === eventType ? "event-type-pill active" : "event-type-pill"}
                style={{ "--event-color": EVENT_COLORS[eventType] ?? "#111723" }}
                onClick={() =>
                  setSelectedEventType(selectedEventType === eventType ? "all" : eventType)
                }
              >
                <span>{formatEventType(eventType)}</span>
                <strong>{eventData.metadata.event_type_counts[eventType]}</strong>
              </button>
            ))}
          </div>
        </section>
      ) : null}

      <section className="timeline-card">
        <div className="timeline-labels">
          <div>
            <span className="eyebrow">Timeline Filter</span>
            <strong>{activeDate ?? "No date"}</strong>
          </div>
          <p>
            {mode === "events"
              ? "Scrub the event boundary. Event records remain visible only if dated on or before the selected date."
              : "Scrub the corpus date boundary. Nodes and edges remain visible only if first seen on or before the selected date."}
          </p>
        </div>
        <input
          className="timeline-slider"
          type="range"
          min="0"
          max={Math.max(TIMELINE_DATES.length - 1, 0)}
          value={selectedDateIndex}
          onChange={(event) => setSelectedDateIndex(Number(event.target.value))}
        />
        <div className="timeline-ticks">
          {timelineTicks(TIMELINE_DATES).map((date) => (
            <span key={date}>{date}</span>
          ))}
        </div>
      </section>

      {mode === "events" ? (
        <EventWorkspace
          events={filteredEvents}
          selectedEvent={selectedEvent}
          selectedEventId={selectedEventId}
          onSelectEvent={setSelectedEventId}
        />
      ) : (
        <main className="main-grid">
          <section className="viewport-card">
            <Suspense fallback={<div className="viewport-loading">Loading visualization...</div>}>
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

          <EdgeInspector selectedEdge={selectedEdge} />
        </main>
      )}
    </div>
  );
}

function EdgeInspector({ selectedEdge }) {
  return (
    <aside className="inspector-card">
      <div className="inspector-header">
        <span className="eyebrow">Evidence Panel</span>
        <h2>{selectedEdge ? selectedEdge.type : "Select an edge"}</h2>
        <p>
          {selectedEdge
            ? `${selectedEdge.source_name} -> ${selectedEdge.target_name}`
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
            <FlagBox flags={selectedEdge.review_flags} />
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
          <p>Try a high-weight blockade or negotiation edge first.</p>
        </div>
      )}
    </aside>
  );
}

function EventWorkspace({ events, selectedEvent, selectedEventId, onSelectEvent }) {
  return (
    <main className="main-grid event-main-grid">
      <section className="event-list-card">
        <div className="event-list-header">
          <div>
            <span className="eyebrow">Event Timeline</span>
            <h2>{events.length} events</h2>
          </div>
          <div className="event-list-summary">
            <span>{events.filter((event) => event.latitude != null).length} mapped</span>
            <span>{events.filter((event) => event.review_flags?.length > 0).length} flagged</span>
          </div>
        </div>

        <div className="event-list">
          {events.length > 0 ? (
            events.map((event) => (
              <button
                key={event.id}
                className={event.id === selectedEventId ? "event-row active" : "event-row"}
                style={{ "--event-color": EVENT_COLORS[event.event_type] ?? "#111723" }}
                onClick={() => onSelectEvent(event.id)}
              >
                <div className="event-row-main">
                  <span className="event-type-chip">{formatEventType(event.event_type)}</span>
                  <strong>{event.summary}</strong>
                  <p>{formatParticipants(event.participants)}</p>
                </div>
                <div className="event-row-side">
                  <span>{event.event_date ?? "No date"}</span>
                  <strong>{formatConfidence(event.confidence)}</strong>
                </div>
              </button>
            ))
          ) : (
            <div className="empty-state">
              <p>No events match the current filters.</p>
            </div>
          )}
        </div>
      </section>

      <EventInspector event={selectedEvent} />
    </main>
  );
}

function EventInspector({ event }) {
  if (!event) {
    return (
      <aside className="inspector-card">
        <div className="inspector-header">
          <span className="eyebrow">Event Inspector</span>
          <h2>Select an event</h2>
          <p>Choose an event from the timeline to inspect evidence and provenance.</p>
        </div>
        <div className="empty-state">
          <p>Nothing selected yet.</p>
        </div>
      </aside>
    );
  }

  return (
    <aside className="inspector-card event-inspector-card">
      <div className="inspector-header">
        <span className="eyebrow">Event Inspector</span>
        <h2>{formatEventType(event.event_type)}</h2>
        <p>{event.summary}</p>
      </div>

      <div className="edge-meta-grid">
        <MetaBlock label="Event Date" value={event.event_date ?? "N/A"} />
        <MetaBlock label="Confidence" value={formatConfidence(event.confidence)} />
        <MetaBlock label="Location" value={event.location || "N/A"} />
        <MetaBlock label="Review" value={event.review_status ?? "unreviewed"} />
      </div>

      <TrustPanel event={event} />

      {event.review_flags?.length > 0 ? <FlagBox flags={event.review_flags} /> : null}

      <section className="event-section">
        <h3>Participants</h3>
        <div className="participant-grid">
          {event.participants.map((participant) => (
            <article
              key={`${participant.name}-${participant.role}`}
              className="participant-card"
              style={{ "--type-color": TYPE_COLORS[participant.type] ?? "#111723" }}
            >
              <span>{participant.role}</span>
              <strong>{participant.name}</strong>
              <small>{participant.type}</small>
            </article>
          ))}
        </div>
      </section>

      <section className="event-section">
        <h3>Compatibility Relations</h3>
        <div className="relation-list">
          {event.relations.map((relation, index) => (
            <article key={`${event.id}-relation-${index}`} className="relation-card">
              <strong>{relation.type}</strong>
              <span>
                {relation.source} {"->"} {relation.target}
              </span>
            </article>
          ))}
        </div>
      </section>

      <section className="event-section">
        <h3>Evidence</h3>
        <blockquote>{event.evidence}</blockquote>
      </section>

      <section className="event-section">
        <h3>Provenance</h3>
        <div className="provenance-grid">
          <MetaBlock label="Article" value={event.article_id ?? "N/A"} />
          <MetaBlock label="Source" value={event.source_publication ?? "N/A"} />
          <MetaBlock label="Published" value={event.published_at ?? "N/A"} />
          <MetaBlock label="Model" value={event.model ?? "N/A"} />
          <MetaBlock label="Prompt" value={event.prompt_version ?? "N/A"} />
          <MetaBlock label="Precision" value={event.date_precision ?? "N/A"} />
        </div>
        {event.source_url ? (
          <a className="source-link" href={event.source_url} target="_blank" rel="noreferrer">
            Open source article
          </a>
        ) : null}
        <article className="evidence-card compact">
          <h3>{event.title}</h3>
        </article>
      </section>
    </aside>
  );
}

function TrustPanel({ event }) {
  const validationStatus = event.validation_status ?? deriveValidationStatus(event);
  const geocodeSource = geocodeSourceLabel(event);
  const confidenceLevel = confidenceLevelLabel(event.confidence);
  const reviewFlagCount = event.review_flags?.length ?? 0;

  const signals = [
    {
      label: "Validation",
      value: formatStatus(validationStatus),
      detail: validationDetail(validationStatus),
      tone: validationStatus === "schema_validated" ? "good" : "warn",
    },
    {
      label: "Evidence",
      value: event.evidence ? "Exact quote" : "Missing",
      detail: event.evidence ? "Validated during extraction" : "No supporting quote",
      tone: event.evidence ? "good" : "bad",
    },
    {
      label: "Source",
      value: event.source_url ? "Linked" : "Missing URL",
      detail: event.source_publication ?? "Unknown source",
      tone: event.source_url ? "good" : "warn",
    },
    {
      label: "Model",
      value: event.model ?? "N/A",
      detail: `Prompt ${event.prompt_version ?? "N/A"}`,
      tone: event.model && event.prompt_version ? "good" : "warn",
    },
    {
      label: "Confidence",
      value: formatConfidence(event.confidence),
      detail: confidenceLevel,
      tone: confidenceTone(event.confidence),
    },
    {
      label: "Geocode",
      value: geocodeSource.value,
      detail: geocodeSource.detail,
      tone: geocodeSource.tone,
    },
    {
      label: "Review Flags",
      value: String(reviewFlagCount),
      detail: reviewFlagCount > 0 ? "Manual review recommended" : "No flags",
      tone: reviewFlagCount > 0 ? "warn" : "good",
    },
  ];

  return (
    <section className="trust-panel">
      <div className="trust-panel-header">
        <h3>Trust Signals</h3>
        <span className={`status-badge ${validationStatus}`}>
          {formatStatus(validationStatus)}
        </span>
      </div>
      <div className="trust-grid">
        {signals.map((signal) => (
          <article key={signal.label} className={`trust-card ${signal.tone}`}>
            <span>{signal.label}</span>
            <strong>{signal.value}</strong>
            <small>{signal.detail}</small>
          </article>
        ))}
      </div>
    </section>
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

function FlagBox({ flags }) {
  return (
    <div className="flag-box">
      {flags.map((flag) => (
        <p key={`${flag.code}-${flag.message}`}>
          <strong>{flag.code}</strong>: {flag.message}
        </p>
      ))}
    </div>
  );
}

function filterEvents({ events, activeDate, eventType, minConfidence, showFlaggedOnly }) {
  return [...events]
    .filter((event) => {
      const visibleByDate = !activeDate || !event.event_date || event.event_date <= activeDate;
      const visibleByType = eventType === "all" || event.event_type === eventType;
      const confidence = typeof event.confidence === "number" ? event.confidence : 0;
      const visibleByConfidence = confidence >= minConfidence;
      const visibleByFlag = !showFlaggedOnly || event.review_flags?.length > 0;
      return visibleByDate && visibleByType && visibleByConfidence && visibleByFlag;
    })
    .sort((left, right) => {
      const dateCompare = String(right.event_date ?? "").localeCompare(String(left.event_date ?? ""));
      if (dateCompare !== 0) {
        return dateCompare;
      }
      return String(left.event_id ?? left.id).localeCompare(String(right.event_id ?? right.id));
    });
}

function timelineTicks(dates) {
  if (dates.length <= 8) {
    return dates;
  }
  const indexes = new Set([0, dates.length - 1]);
  for (let index = 1; index < 6; index += 1) {
    indexes.add(Math.round((index * (dates.length - 1)) / 6));
  }
  return [...indexes].sort((left, right) => left - right).map((index) => dates[index]);
}

function formatEventType(eventType) {
  return String(eventType ?? "Event").replace(/Event$/, " Event");
}

function formatConfidence(value) {
  if (typeof value !== "number") {
    return "N/A";
  }
  return `${Math.round(value * 100)}%`;
}

function confidenceLevelLabel(value) {
  if (typeof value !== "number") {
    return "Unknown confidence";
  }
  if (value >= 0.8) {
    return "High confidence";
  }
  if (value >= 0.55) {
    return "Medium confidence";
  }
  return "Low confidence";
}

function confidenceTone(value) {
  if (typeof value !== "number") {
    return "warn";
  }
  if (value >= 0.8) {
    return "good";
  }
  if (value >= 0.55) {
    return "warn";
  }
  return "bad";
}

function deriveValidationStatus(event) {
  if (!event.evidence) {
    return "missing_evidence";
  }
  if (!Array.isArray(event.participants) || event.participants.length === 0) {
    return "missing_participants";
  }
  if (!Array.isArray(event.relations) || event.relations.length === 0) {
    return "missing_relations";
  }
  if (!event.source_url) {
    return "missing_source_url";
  }
  if (event.location && (event.latitude == null || event.longitude == null)) {
    return "missing_geocode";
  }
  if (event.review_flags?.length > 0) {
    return "needs_review";
  }
  return "schema_validated";
}

function validationDetail(status) {
  const details = {
    schema_validated: "Schema, evidence, and provenance present",
    needs_review: "Review flags are attached",
    missing_evidence: "Supporting quote is missing",
    missing_participants: "Participant roles are missing",
    missing_relations: "Compatibility relations are missing",
    missing_source_url: "Article URL is missing",
    missing_geocode: "Located event has no coordinates",
  };
  return details[status] ?? "Validation status unknown";
}

function formatStatus(status) {
  return String(status ?? "unknown")
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

function geocodeSourceLabel(event) {
  if (!event.location) {
    return { value: "Not applicable", detail: "No event location", tone: "good" };
  }
  if (event.location_geocode_source) {
    return {
      value: event.location_geocode_source,
      detail: event.location_geocode_display_name ?? event.location,
      tone: event.latitude != null && event.longitude != null ? "good" : "warn",
    };
  }
  if (event.latitude != null && event.longitude != null) {
    return { value: "Coordinates only", detail: event.location, tone: "warn" };
  }
  return { value: "Missing", detail: event.location, tone: "bad" };
}

function formatParticipants(participants) {
  if (!Array.isArray(participants) || participants.length === 0) {
    return "No participants";
  }
  return participants
    .slice(0, 3)
    .map((participant) => `${participant.name} (${participant.role})`)
    .join(" / ");
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
