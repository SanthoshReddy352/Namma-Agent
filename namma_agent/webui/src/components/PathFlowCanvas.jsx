import { useMemo } from "react";
import {
  Background, BackgroundVariant, Controls, Handle, MiniMap, Position, ReactFlow,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

// The learning path as a React Flow graph: one generous card per module on a
// pannable, zoomable infinite canvas (drag to pan, wheel/pinch to zoom). Nodes
// keep a fixed comfortable size — the canvas moves, the cards don't shrink.
const NODE_W = 300;
const GAP_X = 380;
const STAGGER_Y = 70;

function ModuleNode({ data }) {
  const { index, title, summary, status, isCurrent } = data;
  const tone = status === "done"
    ? "border-emerald-400/80 bg-emerald-50 dark:bg-emerald-500/10"
    : isCurrent
      ? "border-brand bg-accent-wash ring-4 ring-brand/15"
      : "border-border bg-surface-raised";
  const badge = status === "done"
    ? "bg-emerald-500 text-white"
    : isCurrent ? "bg-brand text-white" : "bg-paper-sink dark:bg-night text-fg-subtle";
  return (
    <div className={`rounded-2xl border-2 px-4 py-3 shadow-soft cursor-pointer transition hover:shadow-pop ${tone}`}
         style={{ width: NODE_W }}>
      <Handle type="target" position={Position.Left} className="!bg-brand-soft !border-0 !h-2.5 !w-2.5" />
      <div className="flex items-center gap-2.5 mb-1.5">
        <span className={`h-7 w-7 shrink-0 grid place-items-center rounded-full text-sm font-semibold ${badge}`}>
          {status === "done" ? "✓" : index + 1}
        </span>
        <span className="text-base font-medium leading-snug text-fg">{title}</span>
      </div>
      {summary && (
        <div className="text-sm leading-snug text-fg-muted line-clamp-3 pl-9">
          {summary}
        </div>
      )}
      <div className="pl-9 mt-1.5 text-2xs uppercase tracking-wider text-fg-subtle">
        {status === "done" ? "Complete" : isCurrent ? "In progress" : "Up next"}
      </div>
      <Handle type="source" position={Position.Right} className="!bg-brand-soft !border-0 !h-2.5 !w-2.5" />
    </div>
  );
}

const nodeTypes = { module: ModuleNode };

export default function PathFlowCanvas({ plan = [], currentId, onOpen, dark = false }) {
  const { nodes, edges } = useMemo(() => {
    const nodes = plan.map((m, i) => ({
      id: m.id,
      type: "module",
      position: { x: i * GAP_X, y: (i % 2) * STAGGER_Y },
      data: {
        index: i, title: m.title, summary: m.summary, status: m.status || "todo",
        isCurrent: m.id === currentId || m.status === "current",
      },
    }));
    const edges = plan.slice(0, -1).map((m, i) => {
      const next = plan[i + 1];
      const active = next.id === currentId || next.status === "current";
      return {
        id: `${m.id}->${next.id}`,
        source: m.id,
        target: next.id,
        type: "smoothstep",
        animated: active,
        style: { strokeWidth: 2.2, stroke: m.status === "done" ? "rgb(var(--success))" : "rgb(var(--flow-idle))" },
      };
    });
    return { nodes, edges };
  }, [plan, currentId]);

  return (
    <div className="h-[440px] rounded-2xl overflow-hidden border border-border bg-bg">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        colorMode={dark ? "dark" : "light"}
        fitView
        fitViewOptions={{ padding: 0.25, maxZoom: 1 }}
        minZoom={0.2}
        maxZoom={1.6}
        panOnScroll
        zoomOnPinch
        nodesDraggable={false}
        nodesConnectable={false}
        elementsSelectable={false}
        proOptions={{ hideAttribution: true }}
        onNodeClick={(_e, node) => {
          const m = plan.find((x) => x.id === node.id);
          if (m) onOpen?.(m);
        }}
      >
        <Background variant={BackgroundVariant.Dots} gap={22} size={1.4} />
        <Controls showInteractive={false} />
        <MiniMap pannable zoomable className="!bg-paper-soft dark:!bg-night-panel"
                 nodeColor={(n) => (n.data?.status === "done" ? "rgb(var(--success))"
                   : n.data?.isCurrent ? "rgb(var(--accent))" : "rgb(var(--flow-idle))")} />
      </ReactFlow>
    </div>
  );
}
