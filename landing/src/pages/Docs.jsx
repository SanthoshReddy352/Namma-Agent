import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import Nav from "../components/Nav.jsx";
import Footer from "../components/Footer.jsx";
import { Code, Diagram, Note, CfgTable } from "../components/DocsKit.jsx";

const D = "/assets/diagrams";

// Sidebar structure — also the scrollspy source of truth.
const NAV = [
  ["Start", [
    ["overview", "Overview"],
    ["getting-started", "Getting started"],
    ["install", "Installation"],
    ["build-ui", "Build the web UI"],
    ["run", "Run it"],
  ]],
  ["Configure", [
    ["config", "Configuration"],
    ["providers", "Models & providers"],
    ["naming", "Name your assistant"],
  ]],
  ["Memory & comms", [
    ["memory", "Engram memory"],
    ["comms", "Telegram & Discord"],
    ["other-setups", "Other setups"],
  ]],
  ["Internals", [
    ["architecture", "Architecture"],
    ["agent-loop", "The agent loop"],
    ["tools", "Tools & approval"],
    ["memory-rag", "Memory & documents"],
    ["learning-room", "Learning Room"],
  ]],
  ["Help", [
    ["testing", "Testing"],
    ["troubleshooting", "Troubleshooting"],
  ]],
];
const ALL_IDS = NAV.flatMap(([, items]) => items.map(([id]) => id));

const reduce = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
function go(id) {
  return (e) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: reduce() ? "auto" : "smooth", block: "start" });
  };
}

function useScrollSpy() {
  const [active, setActive] = useState(ALL_IDS[0]);
  useEffect(() => {
    const sectionElements = ALL_IDS.map(id => document.getElementById(id)).filter(Boolean);
    const handleScroll = () => {
      let currentSectionId = ALL_IDS[0];
      const threshold = window.innerHeight * 0.45;
      for (const el of sectionElements) {
        const rect = el.getBoundingClientRect();
        if (rect.top <= threshold) {
          currentSectionId = el.id;
        } else {
          break;
        }
      }
      setActive(currentSectionId);
    };
    window.addEventListener("scroll", handleScroll, { passive: true });
    handleScroll();
    return () => window.removeEventListener("scroll", handleScroll);
  }, []);
  return active;
}

const navItems = [
  { to: "/", label: "Overview" },
  { to: "/docs", label: "Docs" },
  { href: "https://github.com/SanthoshReddy352/Namma-Agent", label: "GitHub", external: true },
];
const mobileItems = [
  { to: "/", label: "Home" },
  { href: "https://github.com/SanthoshReddy352/Namma-Agent", label: "GitHub", external: true },
];

export default function Docs() {
  const active = useScrollSpy();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  const activeLabel = NAV.flatMap(([_, items]) => items).find(([id]) => id === active)?.[1] || "Overview";

  const go = (id) => (e) => {
    e.preventDefault();
    const el = document.getElementById(id);
    if (el) el.scrollIntoView({ behavior: reduce() ? "auto" : "smooth", block: "start" });
    setMobileMenuOpen(false);
  };

  useEffect(() => {
    if (!active) return;
    const activeLink = document.querySelector(`.docs-side a[href="#${active}"]`);
    const sidebar = document.querySelector(".docs-side");
    if (activeLink && sidebar) {
      const sidebarRect = sidebar.getBoundingClientRect();
      const linkRect = activeLink.getBoundingClientRect();

      let newScrollTop = sidebar.scrollTop;
      if (linkRect.top < sidebarRect.top) {
        newScrollTop += (linkRect.top - sidebarRect.top) - 16;
      } else if (linkRect.bottom > sidebarRect.bottom) {
        newScrollTop += (linkRect.bottom - sidebarRect.bottom) + 16;
      }

      if (newScrollTop !== sidebar.scrollTop) {
        sidebar.scrollTo({ top: newScrollTop, behavior: "smooth" });
      }
    }
  }, [active]);

  return (
    <>
      <Nav items={navItems} cta={{ to: "/", label: "Back to site" }} mobileItems={mobileItems} />

      <main className="shell docs-wrap">
        <div className="docs-grid">
          {/* SIDEBAR */}
          <aside className="docs-side" aria-label="Docs navigation">
            <div className="docs-side__header" onClick={() => setMobileMenuOpen(!mobileMenuOpen)}>
              <span>Menu: <b>{activeLabel}</b></span>
              <svg className={`chevron ${mobileMenuOpen ? "open" : ""}`} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round"><polyline points="6 9 12 15 18 9"></polyline></svg>
            </div>
            <div className={`docs-side__links ${mobileMenuOpen ? "open" : ""}`}>
              {NAV.map(([group, items]) => (
                <div key={group}>
                  <div className="group">{group}</div>
                  {items.map(([id, label]) => (
                    <a key={id} href={`#${id}`} className={active === id ? "active" : ""} onClick={go(id)}>{label}</a>
                  ))}
                </div>
              ))}
            </div>
          </aside>

          {/* CONTENT */}
          <article className="docs-main">
            <div data-reveal>
              <span className="eyebrow">Documentation</span>
              <h1 style={{ marginTop: "var(--s-3)" }}>Namma Agent docs</h1>
              <p className="doc-lead">Everything to install, configure, and understand Namma Agent: a cloud-only personal AI assistant you run yourself. Start at the top, or jump to a section.</p>
            </div>

            {/* OVERVIEW */}
            <section id="overview" className="docs-sec">
              <h2>Overview</h2>
              <p>Namma Agent wraps a single model API call in everything that makes it an agent: one tool-calling loop, a registry of about 85 tools, cross-session memory, project document intelligence, a Learning Room, browser-native voice, and messaging bridges. Everything lives in the <code>namma_agent/</code> Python package, and it runs anywhere Python does.</p>
              <p>The brain is provider-agnostic. Point it at native Anthropic, OpenAI, or Google, or any OpenAI-compatible endpoint such as Ollama or LM Studio, by editing one config key.</p>
              <Note kind="accent" title="Prefer the desktop app">The one-click installers create the environment, install dependencies, configure your first provider, and launch. The manual steps below are for setting it up yourself.</Note>
            </section>

            {/* GETTING STARTED */}
            <section id="getting-started" className="docs-sec">
              <h2>Getting started</h2>
              <p>Three things stand between you and your first chat: a Python environment, an API key for one provider, and the built web UI. The fastest reliable path is server mode, which needs no GUI.</p>
              <ol>
                <li>Create a virtual environment and install the requirements.</li>
                <li>Add an API key to <code>.env</code> and pick the provider in <code>config.yaml</code>.</li>
                <li>Build the web UI once, then run the server and open localhost.</li>
              </ol>
            </section>

            {/* INSTALL */}
            <section id="install" className="docs-sec">
              <h2>Installation</h2>
              <p>From the project root, create the environment and install the dependencies:</p>
              <Code title="bash" code={`python3 -m venv .venv
source .venv/bin/activate            # Windows: .venv\\Scripts\\activate
pip install -r namma_agent/requirements.txt`} />
              <p>Don't need voice or the desktop window? Install just the core plus your provider SDK:</p>
              <Code title="bash" code={`pip install fastapi "uvicorn[standard]" pydantic PyYAML anthropic`} />
              <h3>Add your API key</h3>
              <p>Secrets live in <code>.env</code> at the project root, never in <code>config.yaml</code>.</p>
              <Code title=".env" code={`ANTHROPIC_API_KEY=sk-ant-...
# or OPENAI_API_KEY=... / GOOGLE_API_KEY=...`} />
              <Note title="Local models need no key">Point <code>provider.type</code> at <code>ollama</code> or <code>lmstudio</code> running locally and you can skip the key entirely for a fully offline setup.</Note>
            </section>

            {/* BUILD UI */}
            <section id="build-ui" className="docs-sec">
              <h2>Build the web UI</h2>
              <p>Both the desktop window and <code>--server</code> mode serve a pre-built React bundle from <code>namma_agent/webui/dist</code>. Build it once before the first run, and again after any UI change. Node 18+ is required.</p>
              <Code title="bash" code={`cd namma_agent/webui
npm install        # install JS dependencies
npm run build      # emit namma_agent/webui/dist
cd ../..`} />
              <p>For UI development with hot reload, run <code>npm run dev</code> in <code>namma_agent/webui</code> alongside the server.</p>
            </section>

            {/* RUN */}
            <section id="run" className="docs-sec">
              <h2>Run it</h2>
              <Code title="bash" code={`python -m namma_agent              # native desktop window (pywebview)
python -m namma_agent --server     # backend only — open http://127.0.0.1:8000`} />
              <p>Server mode is the most reliable first run because it has no GUI dependency. The chat UI is at <a className="inline" href="http://127.0.0.1:8000">http://127.0.0.1:8000</a>.</p>
            </section>

            {/* CONFIG */}
            <section id="config" className="docs-sec">
              <h2>Configuration</h2>
              <p>Configuration is layered, so you never have to edit the documented base file to change runtime behaviour:</p>
              <CfgTable rows={[
                ["config.yaml", "The documented, commented base config. Source of defaults."],
                ["config.local.yaml", "UI and runtime overrides, written by the Settings panel. The base file is never rewritten."],
                [".env", "Secrets at the project root: API keys, channel tokens. Never committed."],
                ["NAMMA_CONFIG", "Env var pointing at a different config file entirely."],
              ]} />
              <p>The most important groups in <code>config.yaml</code>:</p>
              <CfgTable rows={[
                ["assistant.name", "The single place to rename the assistant (see below)."],
                ["provider", "The brain: type, model, key variable, fallbacks."],
                ["persona", "Which personas/<id>.yaml shapes the system prompt."],
                ["conversation", "History length, tool-loop limit, auto-approve, default mode."],
                ["memory / database", "Where notes and the SQLite database live."],
                ["security", "Lab mode for scanning tools and the filesystem write policy."],
                ["comms / learning", "Telegram replies, voice transcription, and Learning-Room nudges."],
              ]} />
              <Note title="Tool approval">Sensitive and destructive tools are approval-gated by default. Set <code>conversation.auto_approve: true</code> to run them without prompting.</Note>
            </section>

            {/* PROVIDERS */}
            <section id="providers" className="docs-sec">
              <h2>Models &amp; providers</h2>
              <p>Pick the brain in <code>provider</code>. <code>type</code> is one of <code>anthropic</code>, <code>openai</code>, <code>google</code>, <code>openai_compat</code>, <code>ollama</code>, or <code>lmstudio</code>. The key is read from the environment variable you name in <code>api_key_env</code>.</p>
              <Code title="config.yaml" lang="yaml" code={`provider:
  type: anthropic
  model: claude-opus-4-8
  api_key_env: ANTHROPIC_API_KEY
  max_tokens: 8192
  temperature: 0.3
  # Ordered fallbacks, tried when the primary errors or is down:
  fallback:
    - type: openai_compat
      model: llama-3.3-70b
      base_url: https://api.groq.com/openai/v1
      api_key_env: GROQ_API_KEY
    - type: ollama          # local, no key
      model: llama3.1`} />
              <p>When the primary is unavailable, a <strong>provider chain</strong> falls back across the list automatically, so a single outage doesn't stop a turn.</p>
              <Diagram src={`${D}/provider-chain.png`} alt="Provider chain" caption="The primary brain is tried first; on error or downtime the chain steps down to each fallback in order, while the agent keeps streaming tokens and native tool calls." />
              <h3>Switchable models in the UI</h3>
              <p>Configure several providers (each with its own key) and a curated list of models from <strong>Settings → Providers / Models</strong>. They appear in the picker at the top of every chat; switching mid-conversation starts a new session in the same chat.</p>
              <Code title="config.yaml" lang="yaml" code={`providers:
  - id: anthropic
    type: anthropic
    api_key_env: ANTHROPIC_API_KEY
  - id: groq
    type: openai_compat
    base_url: https://api.groq.com/openai/v1
    api_key_env: GROQ_API_KEY
models:
  - label: Claude Opus
    provider: anthropic
    model: claude-opus-4-8
  - label: Llama 3.3 (Groq)
    provider: groq
    model: llama-3.3-70b`} />
            </section>

            {/* NAMING */}
            <section id="naming" className="docs-sec">
              <h2>Name your assistant</h2>
              <p>The project is Namma Agent, but the assistant you talk to can be called anything. One switch, applied everywhere: the system prompt, the web UI, the voice, and the messaging bridges.</p>
              <Code title="config.yaml" lang="yaml" code={`assistant:
  name: Jarvis`} />
              <p>Or, without editing any file:</p>
              <Code title="bash" code={`ASSISTANT_NAME=Jarvis python -m namma_agent --server`} />
              <Note><code>NAMMA_*</code> environment-variable names (API keys, Telegram tokens) are intentionally left unchanged. They are stable identifiers, not display text.</Note>
            </section>

            {/* MEMORY */}
            <section id="memory" className="docs-sec">
              <h2>Engram memory</h2>
              <p>Long-term memory is built in. Engram stores facts, entities, and the relations between them in the same local SQLite database as your chats, with full-text search and optional embeddings. There is nothing to install and nothing to start.</p>
              <p>Browse, search, and correct what the assistant remembers from the <strong>Memory</strong> tab. Memory writes can be approval-gated, and anything learned from an untrusted channel is quarantined rather than indexed.</p>
              <Note kind="pine" title="External memory engines">Any memory engine that speaks MCP (Mem0, Zep, Cognee, …) can still be attached as an ordinary MCP server under <strong>Settings → MCP</strong>. Its tools appear next to the built-in ones.</Note>
            </section>

            {/* COMMS */}
            <section id="comms" className="docs-sec">
              <h2>Telegram &amp; Discord</h2>
              <p>Chat with your assistant from your phone. The comms bridge polls for inbound messages and routes them through the same agent loop as the web UI, then sends the reply back.</p>
              <Diagram src={`${D}/comms-bridge.png`} alt="Comms bridge" caption="Inbound messages are long-polled and handed to the service; replies go back out the same channel. Telegram voice messages are transcribed first when an STT endpoint is configured." />
              <p>Put the channel tokens in <code>.env</code>, then enable inbound replies in config:</p>
              <Code title=".env" code={`NAMMA_TELEGRAM_TOKEN=123456:ABC-your-bot-token
NAMMA_TELEGRAM_CHAT_ID=your-chat-id
# Discord (optional):
NAMMA_DISCORD_TOKEN=...`} />
              <Code title="config.yaml" lang="yaml" code={`comms:
  inbound_enabled: true        # reply to Telegram messages (polling thread)
  stt:                         # transcribe Telegram voice messages (optional)
    api_key_env: OPENAI_API_KEY
    # base_url: https://api.groq.com/openai/v1
    model: whisper-1`} />
              <Note>Voice in the web UI is 100% browser-native (Web Speech API) and needs no configuration. The STT block above is only for transcribing inbound Telegram <em>voice messages</em>.</Note>
            </section>

            {/* OTHER SETUPS */}
            <section id="other-setups" className="docs-sec">
              <h2>Other setups</h2>
              <h3>Security tools (lab mode)</h3>
              <p>Active scanning tools (<code>port_scan</code>, <code>ping_sweep</code>, <code>dir_enum</code>, <code>dns_enum</code>) are off until you enable lab mode and declare authorized scopes. Enable only on networks you are authorized to test; every scan is approval-gated.</p>
              <Code title="config.yaml" lang="yaml" code={`security:
  lab_mode: true
  authorized_scopes: ["192.168.1.0/24", "lab.example.com"]`} />
              <h3>Smart home (Home Assistant)</h3>
              <p>Off until a URL and token are set. The token lives in <code>.env</code>, named by <code>token_env</code>.</p>
              <Code title="config.yaml" lang="yaml" code={`smart_home:
  url: http://homeassistant.local:8123
  token_env: HASS_TOKEN
  aliases:
    bedroom lights: light.bedroom_main`} />
              <h3>Google Workspace</h3>
              <p>The Gmail and Calendar tools use the <code>gws</code> CLI. Authenticate once with <code>gws auth login</code>, then <code>gmail_list</code>, <code>gmail_send</code>, and <code>calendar_agenda</code> are available.</p>
              <h3>MCP servers</h3>
              <p>Connect external Model Context Protocol tools. Each server's tools appear in the registry as <code>mcp_&lt;server&gt;_&lt;tool&gt;</code>.</p>
              <Code title="config.yaml" lang="yaml" code={`mcp:
  servers:
    - name: filesystem
      command: ["npx","-y","@modelcontextprotocol/server-filesystem","/home/me"]
    - name: git
      command: ["uvx","mcp-server-git"]
      enabled: true`} />
              <Note title="Optional system binaries">Tools degrade gracefully. If <code>nmap</code>, <code>pandoc</code>, <code>tesseract</code>, or Playwright is missing, the tool returns a clear "install X" message instead of crashing.</Note>
            </section>

            {/* ARCHITECTURE */}
            <section id="architecture" className="docs-sec">
              <h2>Architecture</h2>
              <p>One service wires a provider, a tool registry, memory, and document intelligence into a single agent loop. Surfaces (the web UI, voice, and messaging) all feed the same loop, so behaviour is identical no matter where a message comes from.</p>
              <Diagram src={`${D}/architecture-overview.png`} alt="System architecture" caption="Surfaces send messages to the FastAPI service, which drives the agent loop. The loop talks to the provider chain and the capability set: tools, memory, document RAG, and the MCP client." />
              <p>Adding a capability is dropping one file into <code>namma_agent/tools/</code> with a <code>register()</code> function. There is no intent routing graph; the model calls tools natively.</p>
            </section>

            {/* AGENT LOOP */}
            <section id="agent-loop" className="docs-sec">
              <h2>The agent loop</h2>
              <p>A turn is <code>generate → run tools → loop → answer</code>. The model decides what to do, calls tools natively, and the results feed back in until it has an answer to stream. Sensitive tools pass through an approval gate first.</p>
              <Diagram src={`${D}/agent-loop.png`} alt="The agent loop" caption="Each model turn either calls tools or produces the final answer. Tool results are appended and the loop repeats; destructive calls are gated on approval before they run." />
            </section>

            {/* TOOLS */}
            <section id="tools" className="docs-sec">
              <h2>Tools &amp; approval</h2>
              <p>Tools are neutral definitions in a registry: a name, a description, JSON-Schema parameters, and a handler. When the model emits a tool call, the registry looks it up, classifies it, and gates anything sensitive behind your approval (unless auto-approve is on).</p>
              <Diagram src={`${D}/tool-registry.png`} alt="Tool registry & approval" caption="The path from a model tool call to a result: lookup, a safety classification, and an approval gate for destructive actions, with auto-approve as an opt-in bypass." />
            </section>

            {/* MEMORY & RAG */}
            <section id="memory-rag" className="docs-sec">
              <h2>Memory &amp; documents</h2>
              <p>Memory is a single SQLite database: sessions and turns, a full-text <code>facts</code> table (FTS5), and an audit log, plus Markdown notes the assistant curates. Facts and session summaries are recalled across days.</p>
              <Diagram src={`${D}/memory-schema.png`} alt="Memory store" caption="One SQLite database holds sessions, turns, full-text facts, and an audit log; curated USER.md and MEMORY.md notes sit alongside it." />
              <h3>Project document intelligence</h3>
              <p>Group chats into projects and give each one a document shelf. Every upload is text-extracted, screened for prompt injection, chunked structure-aware, and indexed into FTS5. In a project chat, answers are grounded with file and section citations, and flagged files are quarantined out of retrieval until you trust them.</p>
              <Diagram src={`${D}/rag-pipeline.png`} alt="Document RAG pipeline" caption="From upload to grounded answer: extract, screen for injection, chunk, index, and retrieve with BM25 ranking, per-document diversity, and neighbour stitching." />
            </section>

            {/* LEARNING ROOM */}
            <section id="learning-room" className="docs-sec">
              <h2>Learning Room</h2>
              <p>Turn any goal, or an uploaded syllabus, into a structured path. Namma Agent infers your level, builds a module path, and teaches one module at a time, each in its own chat. It assesses through conversation and a module only advances through an explicit confidence gate.</p>
              <Diagram src={`${D}/learning-room.png`} alt="Learning Room flow" caption="A goal becomes a module path. Each module is taught and assessed in conversation; the confidence gate decides whether to revisit or advance." />
            </section>

            {/* TESTING */}
            <section id="testing" className="docs-sec">
              <h2>Testing</h2>
              <p>The full suite runs offline and mocked, so no API key is needed.</p>
              <Code title="bash" code={`python -m pytest namma_agent/tests/ -q`} />
            </section>

            {/* TROUBLESHOOTING */}
            <section id="troubleshooting" className="docs-sec">
              <h2>Troubleshooting</h2>
              <CfgTable rows={[
                ["ModuleNotFoundError: anthropic", "Install your provider SDK: pip install anthropic / openai / google-genai."],
                ["Native window doesn't open", "pywebview missing or no display. Use --server and open the browser."],
                ["Provider/auth errors on first chat", "Key missing or typo in .env, or provider.type doesn't match the key you set."],
                ["MCP server: server closed the connection", "Slow cold start exceeds the default timeout. Set connect_timeout: 90 in the MCP entry."],
              ]} />
              <div className="docs-foot-nav">
                <Link to="/" className="btn btn--secondary">← Back to site</Link>
                <a href="https://github.com/SanthoshReddy352/Namma-Agent" className="btn btn--primary" data-magnetic>Open the repo</a>
              </div>
            </section>
          </article>
        </div>
      </main>

      <Footer />
    </>
  );
}
