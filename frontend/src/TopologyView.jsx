import { useEffect, useRef } from "react";
import cytoscape from "cytoscape";
import { RELATION_COLORS, TYPE_COLORS } from "./graphStyle";

export function TopologyView({ graph, selectedEdgeId, onSelectEdge }) {
  const containerRef = useRef(null);
  const cyRef = useRef(null);

  useEffect(() => {
    if (!containerRef.current) {
      return undefined;
    }

    const cy = cytoscape({
      container: containerRef.current,
      elements: [
        ...graph.nodes.map((node) => ({
          data: {
            id: node.id,
            label: node.name,
            type: node.type,
            articleCount: node.article_count,
            flagged: node.review_flags.length > 0 ? "yes" : "no",
          },
        })),
        ...graph.edges.map((edge) => ({
          data: {
            id: edge.id,
            source: edge.source,
            target: edge.target,
            relationType: edge.type,
            weight: edge.weight,
          },
        })),
      ],
      layout: {
        name: "cose",
        fit: true,
        padding: 24,
        animate: false,
      },
      style: [
        {
          selector: "node",
          style: {
            label: "data(label)",
            "background-color": (ele) => TYPE_COLORS[ele.data("type")] ?? "#333",
            color: "#111",
            "font-family": "Space Grotesk, sans-serif",
            "font-size": 11,
            "text-wrap": "wrap",
            "text-max-width": 120,
            width: (ele) => 26 + Math.min(ele.data("articleCount") * 3, 18),
            height: (ele) => 26 + Math.min(ele.data("articleCount") * 3, 18),
            "border-width": (ele) => (ele.data("flagged") === "yes" ? 3 : 1.5),
            "border-color": "#f6f1e7",
          },
        },
        {
          selector: "edge",
          style: {
            width: (ele) => 1.5 + Math.min(ele.data("weight"), 6),
            "line-color": (ele) => RELATION_COLORS[ele.data("relationType")] ?? "#444",
            "target-arrow-color": (ele) => RELATION_COLORS[ele.data("relationType")] ?? "#444",
            "target-arrow-shape": "triangle",
            "curve-style": "bezier",
            opacity: 0.75,
          },
        },
        {
          selector: "edge:selected",
          style: {
            width: 6,
            opacity: 1,
          },
        },
      ],
    });

    cy.on("tap", "edge", (event) => {
      onSelectEdge(event.target.id());
    });

    cyRef.current = cy;
    return () => {
      cy.destroy();
      cyRef.current = null;
    };
  }, [graph, onSelectEdge]);

  useEffect(() => {
    const cy = cyRef.current;
    if (!cy) {
      return;
    }
    cy.edges().unselect();
    if (selectedEdgeId) {
      const edge = cy.getElementById(selectedEdgeId);
      if (edge) {
        edge.select();
      }
    }
  }, [selectedEdgeId]);

  return <div ref={containerRef} className="network-canvas" />;
}
