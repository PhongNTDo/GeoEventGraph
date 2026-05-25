import { useEffect, useRef } from "react";
import { CircleMarker, MapContainer, Polyline, TileLayer, Tooltip } from "react-leaflet";
import { MAP_CENTER, RELATION_COLORS, RELATION_STYLES, TYPE_COLORS } from "./graphStyle";

export function MapView({ graph, selectedEdgeId, onSelectEdge }) {
  const mapRef = useRef(null);

  useEffect(() => {
    if (!mapRef.current) {
      return;
    }
    const map = mapRef.current;
    requestAnimationFrame(() => map.invalidateSize());
  }, [graph.nodes.length, graph.edges.length]);

  return (
    <MapContainer
      center={MAP_CENTER}
      zoom={4}
      className="map-canvas"
      ref={mapRef}
      zoomControl={false}
      worldCopyJump
    >
      <TileLayer
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
        url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
      />

      {graph.edges
        .filter((edge) => edge.source_coords && edge.target_coords)
        .map((edge) => {
          const style = RELATION_STYLES[edge.type] ?? {};
          return (
            <Polyline
              key={edge.id}
              positions={[edge.source_coords, edge.target_coords]}
              pathOptions={{
                color: RELATION_COLORS[edge.type] ?? "#444",
                weight: selectedEdgeId === edge.id ? (style.weight ?? 3) + 2 : style.weight ?? 3,
                opacity: selectedEdgeId === edge.id ? 0.95 : 0.72,
                dashArray: style.dashArray ?? undefined,
              }}
              eventHandlers={{ click: () => onSelectEdge(edge.id) }}
            >
              <Tooltip sticky>
                <strong>{edge.type}</strong>
                <div>
                  {edge.source_name} → {edge.target_name}
                </div>
                <div>{edge.weight} evidence snippets</div>
              </Tooltip>
            </Polyline>
          );
        })}

      {graph.nodes
        .filter((node) => node.map_latitude != null && node.map_longitude != null)
        .map((node) => (
          <CircleMarker
            key={node.id}
            center={[node.map_latitude, node.map_longitude]}
            radius={
              node.map_position_source === "derived"
                ? 6
                : node.review_flags.length > 0
                  ? 10
                  : 7
            }
            pathOptions={{
              color: "#fdfbf3",
              weight: node.map_position_source === "derived" ? 1 : 1.5,
              fillColor: TYPE_COLORS[node.type] ?? "#333",
              fillOpacity: node.map_position_source === "derived" ? 0.58 : 0.88,
            }}
          >
            <Tooltip direction="top" offset={[0, -10]}>
              <div className="tooltip-title">{node.name}</div>
              <div>{node.type}</div>
              <div>{node.article_count} articles</div>
              <div>
                Position:{" "}
                {node.map_position_source === "geocoded"
                  ? "geocoded"
                  : node.map_position_source === "centroid"
                    ? "country centroid"
                    : node.map_position_source === "derived"
                      ? "derived from connected node"
                      : "unknown"}
              </div>
              {node.review_flags.length > 0 ? <div>Flagged for review</div> : null}
            </Tooltip>
          </CircleMarker>
        ))}
    </MapContainer>
  );
}
