import Nav, { scrollToId } from "../components/Nav.jsx";
import Footer from "../components/Footer.jsx";
import { LogoMark, Arrow, Check, Lines, Brain, Graph, Cap, Chat, Doc, Search } from "../components/icons.jsx";

const sc = (id) => (e) => { e.preventDefault(); scrollToId(id); };

const Mega = (
  <div className="navx__drop" key="mega">
    <button className="navx__link" aria-haspopup="true" aria-expanded="false" data-spy="capabilities,memory,graph,learn">
      Capabilities <svg className="nav-caret" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round"><path d="M6 9l6 6 6-6" /></svg>
    </button>
    <div className="navx__mega" role="menu">
      <div className="navx__mega-grid">
        <a className="mega-item" href="#capabilities" onClick={sc("capabilities")}><span className="ico"><Lines size={20} /></span><div><b>Tools</b><span>~85 native actions</span></div></a>
        <a className="mega-item" href="#memory" onClick={sc("memory")}><span className="ico pine"><Brain size={20} /></span><div><b>Memory</b><span>Facts that persist</span></div></a>
        <a className="mega-item" href="#graph" onClick={sc("graph")}><span className="ico"><Graph size={20} /></span><div><b>Knowledge graph</b><span>Built in, zero setup</span></div></a>
        <a className="mega-item" href="#learn" onClick={sc("learn")}><span className="ico pine"><Cap size={20} /></span><div><b>Learning Room</b><span>One module at a time</span></div></a>
      </div>
      <div className="navx__mega-foot"><span className="muted" style={{ fontSize: "var(--fs-small)" }}>One agent, any brain, your machine</span><a href="#capabilities" onClick={sc("capabilities")}>Explore →</a></div>
    </div>
  </div>
);

const navItems = [
  { id: "top", label: "Overview", spy: true },
  { mega: true },
  { id: "providers", label: "Providers", spy: true },
  { to: "/docs", label: "Docs" },
];
const mobileItems = [
  { id: "capabilities", label: "Capabilities" },
  { id: "graph", label: "Knowledge graph" },
  { id: "providers", label: "Providers" },
  { to: "/docs", label: "Docs" },
  { id: "start", label: "Get started" },
];

export default function Landing() {
  return (
    <div className="landing-wrap">
      <Nav items={navItems} mega={Mega} showCmdk cta={{ id: "start", label: "Run it" }} mobileItems={mobileItems} />

      {/* command palette */}
      <div className="scrim" data-scrim></div>
      <div className="palette" role="dialog" aria-label="Command palette">
        <div className="palette__input">
          <Search size={18} /><input type="text" placeholder="Jump to a section..." aria-label="Search" />
          <kbd style={{ fontFamily: "var(--font-mono)", fontSize: "11px", color: "var(--ink-faint)" }}>esc</kbd>
        </div>
        <div className="palette__list">
          <div className="palette__item" data-go="#capabilities" aria-selected="true"><span className="ico"><Lines size={15} /></span> Capabilities <span className="meta">section</span></div>
          <div className="palette__item" data-go="#graph"><span className="ico"><Graph size={15} /></span> Knowledge graph <span className="meta">section</span></div>
          <div className="palette__item" data-go="#providers"><span className="ico"><svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="3" /></svg></span> Providers <span className="meta">section</span></div>
          <div className="palette__item" data-go="#start"><span className="ico"><Arrow size={15} /></span> Get started <span className="meta">section</span></div>
        </div>
      </div>

      <main>
        {/* HERO */}
        <header className="na-hero" id="top">
          <span className="orb" aria-hidden="true"></span>
          <div className="shell na-hero__grid">
            <div>
              <span className="badge" data-reveal><span className="dot pulse"></span> Cloud-only, runs anywhere Python does</span>
              <h1 className="display" data-reveal style={{ "--reveal-delay": "80ms" }}>A personal AI assistant you actually run yourself.</h1>
              <p className="lead" data-reveal style={{ "--reveal-delay": "160ms" }}>Namma Agent wraps one API call in everything that makes it an agent: a tool-calling loop, memory that lasts, document intelligence, and a learning room. Bring any brain, keep your data on your machine.</p>
              <ul className="lede-list" data-reveal style={{ "--reveal-delay": "220ms" }}>
                <li><Check /> Around 85 tools the model calls natively, no intent regexes.</li>
                <li><Check /> Swap Anthropic for a local Ollama model with one config key.</li>
              </ul>
              <div className="row" data-reveal style={{ "--reveal-delay": "300ms", marginTop: "var(--s-5)", gap: "var(--s-4)" }}>
                <a href="#start" onClick={sc("start")} className="btn btn--primary btn--lg" data-magnetic="0.4">Get started<Arrow /></a>
                <button className="btn btn--secondary btn--lg" data-cmdk-open>Browse capabilities</button>
              </div>
            </div>

            <div data-reveal="right">
              <div className="console tilt" data-tilt="4">
                <div className="console__bar"><i></i><i></i><i></i><span className="who">namma · one turn</span></div>
                <div className="console__body">
                  <div className="msg">
                    <span className="from">You</span>
                    <div className="bubble user">Find last week's invoices, total them, and remind me to send the report on Friday.</div>
                  </div>
                  <div className="msg">
                    <span className="from">Namma · running tools</span>
                    <div className="toolcalls">
                      <span className="toolcall"><span className="tick"><Check size={12} /></span>find_files</span>
                      <span className="toolcall"><span className="tick"><Check size={12} /></span>read_document</span>
                      <span className="toolcall run"><span className="tick"><span className="pixel-loader" style={{ "--pixel": "3px" }}><i></i><i></i><i></i><i></i></span></span>add_reminder</span>
                    </div>
                  </div>
                  <div className="msg">
                    <span className="from">Namma</span>
                    <div className="bubble agent">Found 6 invoices from last week totalling $4,820. I set a reminder for Friday at 9am to send the report.<span className="caret" aria-hidden="true"></span></div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </header>

        {/* TRUST MARQUEE */}
        <div className="shell" data-reveal>
          <div className="marquee-mask">
            <div className="marquee" aria-hidden="true">
              {["Anthropic", "OpenAI", "Google", "Ollama", "LM Studio", "MCP", "OpenRouter", "Anthropic", "OpenAI", "Google", "Ollama", "LM Studio", "MCP", "OpenRouter"].map((n, i) => (
                <span key={i} style={{ fontFamily: "var(--font-display)", fontSize: "1.25rem", color: "var(--ink-faint)" }}>{n}</span>
              ))}
            </div>
          </div>
        </div>

        {/* CAPABILITIES BENTO */}
        <section id="capabilities" className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">What's inside</span><h2>An agent, not a chat box.</h2></div>
          <div className="bento" data-reveal-group data-stagger="90">
            <div className="flex-col tile-accent col-2 flow-sweep" data-reveal data-ambient>
              <div className="b-head"><span className="ico" style={{ background: "rgba(255,255,255,.18)", color: "#fff" }}><Lines /></span> The agent loop</div>
              <div className="b-big">One loop, end to end</div>
              <div className="b-foot">Generate, run tools, loop, answer. The model calls tools natively and streams as it goes.</div>
            </div>
            <div className="flex-col" data-reveal>
              <div className="b-head"><span className="ico"><Lines /></span> Tools</div>
              <div className="b-big" style={{ fontSize: "2.4rem" }}>~85</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "auto" }}>Files, shell, web, vision, scheduler, and more.</p>
            </div>
            <div className="flex-col row-2" id="memory" data-reveal>
              <div className="b-head"><Brain /> Memory that lasts</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", marginTop: "6px" }}>Facts, notes, and session summaries in one SQLite store, recalled across days.</p>
              <div className="chips" style={{ marginTop: "auto" }}><span className="chip-tag solid">remember</span><span className="chip-tag">recall</span><span className="chip-tag">summarize</span></div>
            </div>
            <div className="flex-col tile-ink" data-reveal data-ambient>
              <div className="b-head"><span className="ico" style={{ background: "rgba(255,255,255,.12)", color: "#fff" }}><Chat /></span> Voice & Telegram</div>
              <div className="b-big" style={{ fontSize: "1.85rem" }}>Talk anywhere</div>
              <div className="b-foot">Browser-native voice, plus a Telegram bridge for your phone.</div>
            </div>
            <div className="flex-col col-2" data-reveal>
              <div className="b-head"><Doc /> Projects with document intelligence</div>
              <p className="muted" style={{ fontSize: "var(--fs-small)", margin: "8px 0 auto" }}>Give each project a document shelf. Every upload is screened for prompt injection, chunked, and indexed, so answers come back with file and section citations.</p>
              <div className="row" style={{ justifyContent: "space-between", marginTop: "var(--s-4)" }}><span className="muted" style={{ fontSize: "var(--fs-small)" }}>Indexed and grounded</span><b style={{ fontSize: "var(--fs-small)" }}>25 files / project</b></div>
            </div>
          </div>
        </section>

        {/* KNOWLEDGE GRAPH */}
        <section id="graph" className="section shell">
          <div className="graph-wrap">
            <div data-reveal="left">
              <span className="eyebrow"><span className="pixel-mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>&nbsp; Built-in memory</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>It remembers how things connect.</h2>
              <p className="muted" style={{ maxWidth: "46ch" }}>Engram, the built-in memory, keeps your facts as more than a flat list. People, files, and ideas become entities linked by how they relate, so the assistant can follow a thread instead of guessing. It lives in the same local SQLite database as everything else, with nothing extra to install.</p>
              <ul className="lede-list">
                <li><Check /> Keyword search over everything it has learned, plus optional embeddings.</li>
                <li><Check /> Entities and relationships, not just keywords.</li>
                <li><Check /> Browse and correct it in the Memory tab.</li>
              </ul>
              <div className="row" style={{ marginTop: "var(--s-6)", gap: "var(--s-3)" }}><span className="badge badge--pine"><span className="dot"></span> Engram</span><span className="badge badge--quiet"><span className="dot"></span> local SQLite</span><span className="badge badge--quiet"><span className="dot"></span> no extra deps</span></div>
            </div>
            <div className="graph-card" data-reveal="right" aria-hidden="true">
              <svg viewBox="0 0 420 340" fill="none" xmlns="http://www.w3.org/2000/svg">
                <g stroke="var(--line-strong)" strokeWidth="2">
                  <path d="M210 170 L110 80" /><path d="M210 170 L320 90" /><path d="M210 170 L95 250" /><path d="M210 170 L325 245" /><path d="M110 80 L320 90" /><path d="M95 250 L325 245" /><path d="M320 90 L325 245" />
                </g>
                <g className="gnode-float"><circle cx="110" cy="80" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="110" y="84" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">people</text></g>
                <g className="gnode-float b"><circle cx="320" cy="90" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="320" y="94" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">files</text></g>
                <g className="gnode-float c"><circle cx="95" cy="250" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="95" y="254" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">tasks</text></g>
                <g className="gnode-float b"><circle cx="325" cy="245" r="26" fill="var(--surface-sunken)" stroke="var(--line)" strokeWidth="1.5" /><text x="325" y="249" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--ink-muted)">notes</text></g>
                <g className="gnode-float"><circle cx="210" cy="170" r="34" fill="var(--accent)" /><text x="210" y="166" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="11" fill="var(--accent-ink)">you</text><text x="210" y="180" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="9" fill="color-mix(in srgb, var(--accent-ink) 75%, transparent)">graph</text></g>
              </svg>
              <div className="pixel-corners" style={{ position: "absolute", inset: 0, pointerEvents: "none" }}></div>
            </div>
          </div>
        </section>

        {/* LEARNING ROOM */}
        <section id="learn" className="section shell">
          <div className="suite-grid">
            <div data-reveal="left">
              <span className="eyebrow">Learning Room</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>Turn any goal into a path.</h2>
              <p className="muted" style={{ maxWidth: "46ch" }}>Hand it a goal or a syllabus. Namma Agent infers your level, builds a module path, and teaches one module at a time, each in its own chat. It assesses through conversation, keeps a model of how you think, and only advances on an explicit confidence gate.</p>
              <div className="accordion" data-single="true" style={{ marginTop: "var(--s-6)" }}>
                <div className="acc-item open"><button className="acc-head" aria-expanded="true">Recall warm-ups and a running example <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Each module opens by pulling forward what you already know, then carries one example across the whole path.</p></div></div></div>
                <div className="acc-item"><button className="acc-head" aria-expanded="false">Diagrams and simulations, server-rendered <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Inline diagrams, images, and interactive simulations are produced server-side, so nothing extra runs in your browser.</p></div></div></div>
                <div className="acc-item"><button className="acc-head" aria-expanded="false">Gentle Telegram nudges <span className="plus"></span></button><div className="acc-body"><div><p className="muted">Opt in, and it reminds you about topics that have gone quiet, on your phone.</p></div></div></div>
              </div>
            </div>
            <div data-reveal="right">
              <div className="card" style={{ padding: "var(--pad-card)" }}>
                <div style={{ fontFamily: "var(--font-mono)", fontSize: "var(--fs-micro)", letterSpacing: ".1em", textTransform: "uppercase", color: "var(--ink-faint)", marginBottom: "var(--s-4)" }}>Module path</div>
                <div className="steps" style={{ marginBottom: "var(--s-6)" }}><div className="step done"><span className="num"><Check size={14} /></span><span className="lbl">Basics</span></div><span className="line" style={{ background: "var(--accent)" }}></span><div className="step active"><span className="num">2</span><span className="lbl">Core</span></div><span className="line"></span><div className="step"><span className="num">3</span><span className="lbl">Applied</span></div></div>
                <div className="row" style={{ justifyContent: "space-between", marginBottom: "8px" }}><span className="muted" style={{ fontSize: "var(--fs-small)" }}>Confidence</span><b style={{ fontSize: "var(--fs-small)" }}>on track</b></div>
                <div className="bar"><i style={{ "--p": "64%" }}></i></div>
                <div className="av-row" style={{ marginTop: "var(--s-5)" }}><span className="badge badge--quiet"><span className="dot"></span> Socratic hints</span><span className="badge badge--pine" style={{ marginLeft: "8px" }}><span className="dot"></span> learner model</span></div>
              </div>
            </div>
          </div>
        </section>

        {/* PROVIDERS */}
        <section id="providers" className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">One agent, any brain</span><h2>Bring the model you trust.</h2></div>
          <div className="providers" data-reveal-group data-stagger="70">
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M13.827 3.52h3.603L24 20h-3.603l-6.57-16.48zm-7.258 0h3.767L16.906 20h-3.674l-1.343-3.461H5.017l-1.344 3.46H0L6.57 3.522zm4.132 9.959L8.453 7.687 6.205 13.48H10.7z" />
                </svg>
              </span>
              <div><b>Anthropic</b><span>Claude, native</span></div>
            </div>
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M9.205 8.658v-2.26c0-.19.072-.333.238-.428l4.543-2.616c.619-.357 1.356-.523 2.117-.523 2.854 0 4.662 2.212 4.662 4.566 0 .167 0 .357-.024.547l-4.71-2.759a.797.797 0 00-.856 0l-5.97 3.473zm10.609 8.8V12.06c0-.333-.143-.57-.429-.737l-5.97-3.473 1.95-1.118a.433.433 0 01.476 0l4.543 2.617c1.309.76 2.189 2.378 2.189 3.948 0 1.808-1.07 3.473-2.76 4.163zM7.802 12.703l-1.95-1.142c-.167-.095-.239-.238-.239-.428V5.899c0-2.545 1.95-4.472 4.591-4.472 1 0 1.927.333 2.712.928L8.23 5.067c-.285.166-.428.404-.428.737v6.898zM12 15.128l-2.795-1.57v-3.33L12 8.658l2.795 1.57v3.33L12 15.128zm1.796 7.23c-1 0-1.927-.332-2.712-.927l4.686-2.712c.285-.166.428-.404.428-.737v-6.898l1.974 1.142c.167.095.238.238.238.428v5.233c0 2.545-1.974 4.472-4.614 4.472zm-5.637-5.303l-4.544-2.617c-1.308-.761-2.188-2.378-2.188-3.948A4.482 4.482 0 014.21 6.327v5.423c0 .333.143.571.428.738l5.947 3.449-1.95 1.118a.432.432 0 01-.476 0zm-.262 3.9c-2.688 0-4.662-2.021-4.662-4.519 0-.19.024-.38.047-.57l4.686 2.71c.286.167.571.167.856 0l5.97-3.448v2.26c0 .19-.07.333-.237.428l-4.543 2.616c-.619.357-1.356.523-2.117.523zm5.899 2.83a5.947 5.947 0 005.827-4.756C22.287 18.339 24 15.84 24 13.296c0-1.665-.713-3.282-1.998-4.448.119-.5.19-.999.19-1.498 0-3.401-2.759-5.947-5.946-5.947-.642 0-1.26.095-1.88.31A5.962 5.962 0 0010.205 0a5.947 5.947 0 00-5.827 4.757C1.713 5.447 0 7.945 0 10.49c0 1.666.713 3.283 1.998 4.448-.119.5-.19 1-.19 1.499 0 3.401 2.759 5.946 5.946 5.946.642 0 1.26-.095 1.88-.309a5.96 5.96 0 004.162 1.713z" />
                </svg>
              </span>
              <div><b>OpenAI</b><span>GPT, native</span></div>
            </div>
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M20.616 10.835a14.147 14.147 0 01-4.45-3.001 14.111 14.111 0 01-3.678-6.452.503.503 0 00-.975 0 14.134 14.134 0 01-3.679 6.452 14.155 14.155 0 01-4.45 3.001c-.65.28-1.318.505-2.002.678a.502.502 0 000 .975c.684.172 1.35.397 2.002.677a14.147 14.147 0 014.45 3.001 14.112 14.112 0 013.679 6.453.502.502 0 00.975 0c.172-.685.397-1.351.677-2.003a14.145 14.145 0 013.001-4.45 14.113 14.113 0 016.453-3.678.503.503 0 000-.975 13.245 13.245 0 01-2.003-.678z" />
                </svg>
              </span>
              <div><b>Google</b><span>Gemini, native</span></div>
            </div>
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M7.905 1.09c.216.085.411.225.588.41.295.306.544.744.734 1.263.191.522.315 1.1.362 1.68a5.054 5.054 0 012.049-.636l.051-.004c.87-.07 1.73.087 2.48.474.101.053.2.11.297.17.05-.569.172-1.134.36-1.644.19-.52.439-.957.733-1.264a1.67 1.67 0 01.589-.41c.257-.1.53-.118.796-.042.401.114.745.368 1.016.737.248.337.434.769.561 1.287.23.934.27 2.163.115 3.645l.053.04.026.019c.757.576 1.284 1.397 1.563 2.35.435 1.487.216 3.155-.534 4.088l-.018.021.002.003c.417.762.67 1.567.724 2.4l.002.03c.064 1.065-.2 2.137-.814 3.19l-.007.01.01.024c.472 1.157.62 2.322.438 3.486l-.006.039a.651.651 0 01-.747.536.648.648 0 01-.54-.742c.167-1.033.01-2.069-.48-3.123a.643.643 0 01.04-.617l.004-.006c.604-.924.854-1.83.8-2.72-.046-.779-.325-1.544-.8-2.273a.644.644 0 01.18-.886l.009-.006c.243-.159.467-.565.58-1.12a4.229 4.229 0 00-.095-1.974c-.205-.7-.58-1.284-1.105-1.683-.595-.454-1.383-.673-2.38-.61a.653.653 0 01-.632-.371c-.314-.665-.772-1.141-1.343-1.436a3.288 3.288 0 00-1.772-.332c-1.245.099-2.343.801-2.67 1.686a.652.652 0 01-.61.425c-1.067.002-1.893.252-2.497.703-.522.39-.878.935-1.066 1.588a4.07 4.07 0 00-.068 1.886c.112.558.331 1.02.582 1.269l.008.007c.212.207.257.53.109.785-.36.622-.629 1.549-.673 2.44-.05 1.018.186 1.902.719 2.536l.016.019a.643.643 0 01.095.69c-.576 1.236-.753 2.252-.562 3.052a.652.652 0 01-1.269.298c-.243-1.018-.078-2.184.473-3.498l.014-.035-.008-.012a4.339 4.339 0 01-.598-1.309l-.005-.019a5.764 5.764 0 01-.177-1.785c.044-.91.278-1.842.622-2.59l.012-.026-.002-.002c-.293-.418-.51-.953-.63-1.545l-.005-.024a5.352 5.352 0 01.093-2.49c.262-.915.777-1.701 1.536-2.269.06-.045.123-.09.186-.132-.159-1.493-.119-2.73.112-3.67.127-.518.314-.95.562-1.287.27-.368.614-.622 1.015-.737.266-.076.54-.059.797.042zm4.116 9.09c.936 0 1.8.313 2.446.855.63.527 1.005 1.235 1.005 1.94 0 .888-.406 1.58-1.133 2.022-.62.375-1.451.557-2.403.557-1.009 0-1.871-.259-2.493-.734-.617-.47-.963-1.13-.963-1.845 0-.707.398-1.417 1.056-1.946.668-.537 1.55-.849 2.485-.849zm0 .896a3.07 3.07 0 00-1.916.65c-.461.37-.722.835-.722 1.25 0 .428.21.829.61 1.134.455.347 1.124.548 1.943.548.799 0 1.473-.147 1.932-.426.463-.28.7-.686.7-1.257 0-.423-.246-.89-.683-1.256-.484-.405-1.14-.643-1.864-.643zm.662 1.21l.004.004c.12.151.095.37-.056.49l-.292.23v.446a.375.375 0 01-.376.373.375.375 0 01-.376-.373v-.46l-.271-.218a.347.347 0 01-.052-.49.353.353 0 01.494-.051l.215.172.22-.174a.353.353 0 01.49.051zm-5.04-1.919c.478 0 .867.39.867.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872zm8.706 0c.48 0 .868.39.868.871a.87.87 0 01-.868.871.87.87 0 01-.867-.87.87.87 0 01.867-.872zM7.44 2.3l-.003.002a.659.659 0 00-.285.238l-.005.006c-.138.189-.258.467-.348.832-.17.692-.216 1.631-.124 2.782.43-.128.899-.208 1.404-.237l.01-.001.019-.034c.046-.082.095-.161.148-.239.123-.771.022-1.692-.253-2.444-.134-.364-.297-.65-.453-.813a.628.628 0 00-.107-.09L7.44 2.3zm9.174.04l-.002.001a.628.628 0 00-.107.09c-.156.163-.32.45-.453.814-.29.794-.387 1.776-.23 2.572l.058.097.008.014h.03a5.184 5.184 0 011.466.212c.086-1.124.038-2.043-.128-2.722-.09-.365-.21-.643-.349-.832l-.004-.006a.659.659 0 00-.285-.239h-.004z" />
                </svg>
              </span>
              <div><b>Ollama</b><span>Local, no key</span></div>
            </div>
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="currentColor">
                  <path d="M2.84 2a1.273 1.273 0 100 2.547h14.107a1.273 1.273 0 100-2.547H2.84zM7.935 5.33a1.273 1.273 0 000 2.548H22.04a1.274 1.274 0 000-2.547H7.935zM3.624 9.935c0-.704.57-1.274 1.274-1.274h14.106a1.274 1.274 0 010 2.547H4.898c-.703 0-1.274-.57-1.274-1.273zM1.273 12.188a1.273 1.273 0 100 2.547H15.38a1.274 1.274 0 000-2.547H1.273zM3.624 16.792c0-.704.57-1.274 1.274-1.274h14.106a1.273 1.273 0 110 2.547H4.898c-.703 0-1.274-.57-1.274-1.273zM13.029 18.849a1.273 1.273 0 100 2.547h9.698a1.273 1.273 0 100-2.547h-9.698z" fillOpacity=".3"></path>
                  <path d="M2.84 2a1.273 1.273 0 100 2.547h10.287a1.274 1.274 0 000-2.547H2.84zM7.935 5.33a1.273 1.273 0 000 2.548H18.22a1.274 1.274 0 000-2.547H7.935zM3.624 9.935c0-.704.57-1.274 1.274-1.274h10.286a1.273 1.273 0 010 2.547H4.898c-.703 0-1.274-.57-1.274-1.273zM1.273 12.188a1.273 1.273 0 100 2.547H11.56a1.274 1.274 0 000-2.547H1.273zM3.624 16.792c0-.704.57-1.274 1.274-1.274h10.286a1.273 1.273 0 110 2.547H4.898c-.703 0-1.274-.57-1.274-1.273zM13.029 18.849a1.273 1.273 0 100 2.547h5.78a1.273 1.273 0 100-2.547h-5.78z"></path>
                </svg>
              </span>
              <div><b>LM Studio</b><span>Local, no key</span></div>
            </div>
            <div className="card provider" data-reveal>
              <span className="ico">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <rect x="16" y="16" width="6" height="6" rx="1" />
                  <rect x="2" y="16" width="6" height="6" rx="1" />
                  <rect x="9" y="2" width="6" height="6" rx="1" />
                  <path d="M12 8v4M12 12H5v4M12 12h7v4" />
                </svg>
              </span>
              <div><b>OpenAI-compatible</b><span>Any base URL</span></div>
            </div>
          </div>
          <p className="muted" data-reveal style={{ textAlign: "center", marginTop: "var(--s-6)", fontSize: "var(--fs-small)" }}>A provider chain falls back across these automatically when one is down. Local Ollama or LM Studio need no key, for a fully offline setup.</p>
        </section>

        {/* HOW IT WORKS */}
        <section className="section shell">
          <div className="section-head" data-reveal><span className="eyebrow">How a turn works</span><h2>Four steps, on every message.</h2></div>
          <div className="flow" data-reveal-group data-stagger="80">
            <div className="card step-card" data-reveal><div className="n">01</div><h3>Generate</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>The model reads the turn and decides what to do.</p></div>
            <div className="card step-card" data-reveal><div className="n">02</div><h3>Run tools</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>It calls tools natively. Sensitive ones are approval gated.</p></div>
            <div className="card step-card" data-reveal><div className="n">03</div><h3>Loop</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>Results feed back in, and it chains the next step.</p></div>
            <div className="card step-card" data-reveal><div className="n">04</div><h3>Answer</h3><p className="muted" style={{ fontSize: "var(--fs-small)" }}>Tokens stream to the UI as the answer comes together.</p></div>
          </div>
        </section>

        {/* QUICKSTART / CTA */}
        <section id="start" className="section shell">
          <div className="quickstart">
            <div data-reveal="left">
              <span className="eyebrow">Get started</span>
              <h2 style={{ margin: "var(--s-3) 0 var(--s-4)" }}>Up and running in a minute.</h2>
              <p className="muted" style={{ maxWidth: "44ch" }}>Install the core, add a key for the provider you want, and open the chat at localhost. The server mode is the most reliable first run, no GUI needed.</p>
              <div className="row" style={{ marginTop: "var(--s-6)", gap: "var(--s-4)" }}>
                <a href="https://github.com/SanthoshReddy352/Namma-Agent" className="btn btn--primary btn--lg" data-magnetic data-toast="success">View on GitHub<Arrow /></a>
                <a href="#/docs" className="btn btn--secondary btn--lg">Read the docs</a>
              </div>
            </div>
            <div data-reveal="right">
              <div className="term tilt" data-tilt="3">
                <div className="term__bar"><i></i><i></i><i></i><span className="tag">bash</span></div>
                <pre>
<span className="pl"># install the core + your provider</span>{"\n"}
pip install -r namma_agent/requirements.txt{"\n\n"}
<span className="pl"># add your key</span>{"\n"}
cp namma_agent/.env.example .env{"\n"}
<span className="ac">ANTHROPIC_API_KEY</span>=sk-ant-...{"\n\n"}
<span className="pl"># run it</span>{"\n"}
python -m namma_agent --server{"\n"}
<span className="ok">→ chat ready at http://127.0.0.1:8000</span>
                </pre>
              </div>
            </div>
          </div>

          <div className="pixel-band pixel-corners" data-reveal="scale" style={{ textAlign: "center", marginTop: "var(--section-y-sm)" }}>
            <div className="pixel-field" aria-hidden="true"></div>
            <span className="eyebrow"><span className="pixel-mark" aria-hidden="true"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></span>&nbsp; Your agent, your advantage</span>
            <h2 style={{ margin: "var(--s-3) auto var(--s-4)", maxWidth: "22ch" }}>Intelligence for everyone, kept on your own machine.</h2>
            <p className="muted" style={{ marginInline: "auto", maxWidth: "46ch" }}>Name it whatever you like, point it at any model, and make it yours.</p>
            <div className="row" style={{ justifyContent: "center", marginTop: "var(--s-6)" }}><a href="#top" onClick={sc("top")} className="btn btn--primary btn--lg" data-magnetic>Run it now</a><a href="#/docs" className="btn btn--secondary btn--lg">Read the docs</a></div>
          </div>
        </section>
      </main>

      <Footer />
    </div>
  );
}
