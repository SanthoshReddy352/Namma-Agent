import { useContext, useEffect, useState } from "react";
import { MessageProcessor } from "@a2ui/web_core";
import { basicCatalog } from "@a2ui/web_core/v0_9/basic_catalog";
import { A2uiSurface } from "@a2ui/react";
import { UiActionContext } from "./A2uiBlock.jsx";
import { RenderSessionContext } from "./Visuals.jsx";
import { reportRenderError } from "../api.js";

// The lazily-loaded half of the A2UI spike: feeds the (server-validated) v0.9
// messages to the official MessageProcessor and renders every surface with
// <A2uiSurface>. Lives in its own chunk — see the bundle numbers in PROGRESS.md.
export default function A2uiSurfaceImpl({ messages, source }) {
  const onAction = useContext(UiActionContext);
  const sessionId = useContext(RenderSessionContext);
  const [state, setState] = useState({ processor: null, surfaces: [], error: null });

  useEffect(() => {
    let processor;
    try {
      processor = new MessageProcessor([basicCatalog], (action) => {
        // {name, surfaceId, sourceComponentId, timestamp, context}
        onAction?.(action);
      });
      processor.processMessages(messages);
      const surfaces = Array.from(processor.model.surfacesMap.values());
      setState({ processor, surfaces, error: null });
    } catch (e) {
      setState({ processor: null, surfaces: [], error: e });
      reportRenderError({ session_id: sessionId, kind: "a2ui",
                          error: String(e?.message || e).slice(0, 500), snippet: String(source).slice(0, 400) });
    }
    return () => { try { processor?.dispose(); } catch { /* already gone */ } };
  }, [source]); // eslint-disable-line react-hooks/exhaustive-deps

  if (state.error) {
    return <div className="text-sm text-warning">Couldn't render this interface: {String(state.error.message || state.error).slice(0, 200)}</div>;
  }
  return (
    <div className="a2ui-container text-fg">
      {state.surfaces.map((surface) => <A2uiSurface key={surface.id} surface={surface} />)}
    </div>
  );
}
