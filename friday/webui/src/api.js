import { useCallback, useEffect, useRef, useState } from "react";

function wsURL() {
  const proto = location.protocol === "https:" ? "wss" : "ws";
  // Dev (vite :5173) proxies /ws to the backend; prod serves same-origin.
  return `${proto}://${location.host}/ws`;
}

export async function fetchConfig() {
  try {
    const r = await fetch("/api/config");
    return await r.json();
  } catch {
    return null;
  }
}

export async function setPersona(id) {
  await fetch("/api/persona", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ id }),
  });
}

let _id = 0;
const nextId = () => `m${++_id}`;

/** Core hook: manages the WebSocket, message list, live timeline, approvals. */
export function useFriday() {
  const [connected, setConnected] = useState(false);
  const [messages, setMessages] = useState([]);
  const [timeline, setTimeline] = useState([]); // events for the in-flight turn
  const [status, setStatus] = useState("idle"); // idle | thinking | done
  const [approval, setApproval] = useState(null);
  const sessionRef = useRef(null);
  const wsRef = useRef(null);
  const streamRef = useRef(null); // id of the assistant message being streamed

  const connect = useCallback(() => {
    const ws = new WebSocket(wsURL());
    wsRef.current = ws;
    ws.onopen = () => setConnected(true);
    ws.onclose = () => {
      setConnected(false);
      setTimeout(connect, 1500); // auto-reconnect
    };
    ws.onmessage = (e) => handle(JSON.parse(e.data));
  }, []);

  useEffect(() => {
    connect();
    return () => wsRef.current && wsRef.current.close();
  }, [connect]);

  function ensureAssistant() {
    if (streamRef.current) return streamRef.current;
    const id = nextId();
    streamRef.current = id;
    setMessages((m) => [...m, { id, role: "assistant", content: "" }]);
    return id;
  }

  function handle(msg) {
    switch (msg.type) {
      case "token": {
        const id = ensureAssistant();
        setMessages((m) => m.map((x) => (x.id === id ? { ...x, content: x.content + msg.text } : x)));
        break;
      }
      case "preamble":
        setTimeline((t) => [...t, { kind: "preamble", text: msg.text }]);
        break;
      case "tool_started":
        setTimeline((t) => [...t, { kind: "tool", tool: msg.tool, args: msg.args, state: "running" }]);
        break;
      case "tool_finished":
        setTimeline((t) => {
          const copy = [...t];
          for (let i = copy.length - 1; i >= 0; i--) {
            if (copy[i].kind === "tool" && copy[i].tool === msg.tool && copy[i].state === "running") {
              copy[i] = { ...copy[i], state: msg.ok ? "ok" : "fail", summary: msg.summary };
              break;
            }
          }
          return copy;
        });
        break;
      case "approval_request":
        setApproval({ id: msg.id, tool: msg.tool, args: msg.args });
        break;
      case "turn_result": {
        sessionRef.current = msg.session_id;
        const id = ensureAssistant();
        setMessages((m) => m.map((x) => (x.id === id ? { ...x, content: msg.content || x.content, tools: msg.tools_used } : x)));
        streamRef.current = null;
        setStatus("idle");
        break;
      }
      case "error":
        setMessages((m) => [...m, { id: nextId(), role: "error", content: msg.message }]);
        streamRef.current = null;
        setStatus("idle");
        break;
      default:
        break;
    }
  }

  const send = useCallback((text) => {
    if (!text.trim() || !wsRef.current || wsRef.current.readyState !== 1) return;
    setMessages((m) => [...m, { id: nextId(), role: "user", content: text }]);
    setTimeline([]);
    streamRef.current = null;
    setStatus("thinking");
    wsRef.current.send(JSON.stringify({ type: "user_input", text, session_id: sessionRef.current }));
  }, []);

  const respondApproval = useCallback((approved) => {
    if (approval && wsRef.current) {
      wsRef.current.send(JSON.stringify({ type: "approval_response", id: approval.id, approved }));
    }
    setApproval(null);
  }, [approval]);

  return { connected, messages, timeline, status, approval, send, respondApproval };
}
