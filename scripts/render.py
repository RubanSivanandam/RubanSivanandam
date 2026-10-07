#!/usr/bin/env python3
"""Render every self-hosted SVG on the profile and refresh the README's live block.

Stdlib only. Run by .github/workflows/profile.yml every 6 hours; runs locally too:
    python scripts/render.py
Live data (contribution calendar, repos, public events) is fetched from GitHub. If a
fetch fails, the SVGs that depend on it are left as they are rather than drawn empty.
"""
import datetime as dt
import html
import json
import math
import os
import random
import re
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

USER = "RubanSivanandam"
ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
README = ROOT / "README.md"
TOKEN = os.environ.get("GITHUB_TOKEN", "")

# ── design tokens ────────────────────────────────────────────────────────────
PANEL, LINE, TEXT, MUTED = "#0D1320", "#1E293B", "#E6EDF3", "#8B98A9"
VIOLET, CYAN, PINK, GREEN, AMBER = "#8B5CF6", "#22D3EE", "#F472B6", "#34D399", "#FBBF24"
HEAT = ["#161B26", "#2E1065", "#5B21B6", "#8B5CF6", "#22D3EE"]
MONO = "'JetBrains Mono','SFMono-Regular',Consolas,Menlo,monospace"
SANS = "'Segoe UI',Inter,'Helvetica Neue',Arial,sans-serif"
CH = 8.4  # approx. advance of a 14px monospace glyph

AGENT_PATTERNS = [  # (name, one-line idea, arXiv id) — rotates daily on concept.svg
    ("ReAct", "Interleave reasoning traces with tool actions, so each step can be grounded in what the last one observed.", "2210.03629"),
    ("Reflexion", "Agents improve across attempts by writing verbal self-critique into memory instead of updating weights.", "2303.11366"),
    ("Toolformer", "A language model teaches itself when to call an API, which one, and how to use the result.", "2302.04761"),
    ("Tree of Thoughts", "Search over branching reasoning paths, with the model evaluating and backtracking between them.", "2305.10601"),
    ("Self-Refine", "Generate, critique, revise: one model iterates on its own output using its own feedback.", "2303.17651"),
    ("Voyager", "A lifelong-learning agent that grows a reusable library of executable skills as it explores.", "2305.16291"),
    ("Generative Agents", "A memory stream plus reflection plus planning yields believable, long-running agent behaviour.", "2304.03442"),
    ("MemGPT", "Treat the context window like RAM: an OS-style manager pages memory in and out for the model.", "2310.08560"),
    ("Chain-of-Thought", "Prompting a model to show intermediate reasoning steps sharply improves multi-step problems.", "2201.11903"),
    ("Self-Consistency", "Sample many reasoning paths and keep the answer they agree on most often.", "2203.11171"),
    ("Retrieval-Augmented Generation", "Pair a generator with a retriever so answers are conditioned on fetched evidence.", "2005.11401"),
    ("Constitutional AI", "Train for harmlessness with AI feedback measured against a written set of principles.", "2212.08073"),
    ("AutoGen", "Build applications as conversations between configurable, tool-using agents.", "2308.08155"),
    ("Program-Aided LMs", "Let the model write a program and offload the actual computation to an interpreter.", "2211.10435"),
    ("Lost in the Middle", "Long-context models use information at the edges of the prompt far better than the middle.", "2307.03172"),
    ("SWE-bench", "Evaluate agents on real GitHub issues: the patch has to make the repository's own tests pass.", "2310.06770"),
    ("GAIA", "Questions simple for humans but hard for agents: browsing, tools and multi-step reasoning together.", "2311.12983"),
]

PROJECTS = [
    dict(slug="aura", name="AURA", tag="Agentic Unified Reasoning Architecture", accent=VIOLET,
         bullets=["CPU-only, BYOK, self-hosted multi-agent runtime on Claude",
                  "Swarm topologies: hierarchical, pipeline, debate, market",
                  "Zero-Trust: agent identity, memory integrity, egress gates",
                  "OWL/RDF ontology + SPARQL + SHACL knowledge layer"],
         chips=["Python", "Claude", "MCP", "rdflib"]),
    dict(slug="pyydl", name="pyydl_mcp", tag="Factory data → Claude, safely", accent=CYAN,
         bullets=["Production MCP server over live garment-plant data",
                  "India · Bangladesh · Sri Lanka · Jordan in one connector",
                  "SQL guardrail rejects writes and cross-schema joins",
                  "Self-correcting agent: repair loop on SQL errors"],
         chips=["Python", "MCP", "SQL Server", "Agents"]),
    dict(slug="po", name="po-ai-extractor", tag="LLM document intelligence", accent=PINK,
         bullets=["Purchase-order extraction driven by YAML schemas",
                  "Grounding checks on every extracted field",
                  "Validation UI for reviewing what the model read",
                  "Tested against the real backend message shapes"],
         chips=["Python", "React", "Vite", "LLM"]),
    dict(slug="wms", name="WMS Mobile Suite", tag="Apps for the factory floor", accent=GREEN,
         bullets=["Inspection, material issue and maintenance apps",
                  "Bluetooth meter integration on the shop floor",
                  "Microsoft Teams notifications for the plant team",
                  "Built with Flutter + Bloc state management"],
         chips=["Flutter", "Dart", "Bloc", "BLE"]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def svg(w, h, body, css="", defs=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none">'
        f"<style>text{{font-family:{SANS}}}.m{{font-family:{MONO}}}{css}</style>"
        f'<defs><linearGradient id="brand" x1="0" y1="0" x2="1" y2="0">'
        f'<stop offset="0" stop-color="{VIOLET}"/><stop offset=".5" stop-color="{CYAN}"/><stop offset="1" stop-color="{PINK}"/></linearGradient>'
        f'<filter id="glow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="4" result="b"/>'
        f'<feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>{defs}</defs>'
        f"{body}</svg>"
    )


def panel(w, h, r=18):
    return (f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="{r}" fill="{PANEL}" stroke="{LINE}"/>'
            f'<rect x="1" y="1" width="{w-2}" height="{h-2}" rx="{r}" fill="url(#dots)" opacity=".5"/>')


DOTS = f'<pattern id="dots" width="22" height="22" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="{LINE}"/></pattern>'


def chrome(title):
    dots = "".join(f'<circle cx="{26+i*18}" cy="26" r="5.5" fill="{c}"/>'
                   for i, c in enumerate(["#FF5F57", "#FEBC2E", "#28C840"]))
    return dots + f'<text x="92" y="30.5" class="m" font-size="12" fill="{MUTED}">{esc(title)}</text>'


def write(name, content):
    ET.fromstring(content)  # GitHub shows nothing for malformed XML; fail the run instead
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / name).write_text(content, encoding="utf-8")
    print(f"  wrote assets/{name} ({len(content):,} bytes)")


# ── static components ────────────────────────────────────────────────────────
def hero():
    w, h = 1000, 360
    rnd = random.Random(29)
    nodes = [(rnd.uniform(770, 975), rnd.uniform(60, 330)) for _ in range(26)]
    edges = "".join(
        f'<line x1="{a[0]:.0f}" y1="{a[1]:.0f}" x2="{b[0]:.0f}" y2="{b[1]:.0f}" stroke="{VIOLET}" stroke-opacity=".28"/>'
        for i, a in enumerate(nodes) for b in nodes[i + 1:] if math.dist(a, b) < 95)
    pts = "".join(
        f'<circle cx="{x:.0f}" cy="{y:.0f}" r="{rnd.choice([2, 2.5, 3.5])}" fill="{rnd.choice([CYAN, VIOLET, PINK])}" '
        f'class="pulse" style="animation-delay:{rnd.uniform(0, 4):.2f}s"/>' for x, y in nodes)
    roles = ["multi-agent swarms", "MCP servers for factories", "zero-trust guardrails",
             "self-improving eval loops"]
    role_txt = "".join(
        f'<text x="{60+CH*1.43*11:.0f}" y="232" class="m role" font-size="20" fill="{CYAN}" '
        f'style="animation-delay:{i*3}s">{esc(r)}</text>' for i, r in enumerate(roles))
    chips, x = "", 60
    for label, col in [("● online", GREEN), ("4 countries · 1 data plane", CYAN),
                       ("Claude · MCP · Python · Flutter", VIOLET), ("UTC+05:30", PINK)]:
        cw = len(label) * 7.3 + 26
        chips += (f'<rect x="{x}" y="282" width="{cw:.0f}" height="30" rx="15" fill="{col}" fill-opacity=".1" stroke="{col}" stroke-opacity=".5"/>'
                  f'<text x="{x+13}" y="301.5" class="m" font-size="12" fill="{col}">{esc(label)}</text>')
        x += cw + 10
    name = "RUBAN SIVANANDAM"
    css = (
        ".pulse{animation:pulse 4s ease-in-out infinite;transform-box:fill-box;transform-origin:center}"
        "@keyframes pulse{0%,100%{opacity:.35;transform:scale(1)}50%{opacity:1;transform:scale(1.8)}}"
        ".role{opacity:0;animation:role 12s infinite}"
        "@keyframes role{0%{opacity:0;transform:translateY(10px)}4%,21%{opacity:1;transform:translateY(0)}25%,100%{opacity:0;transform:translateY(-10px)}}"
        ".g1{animation:g1 5s steps(1) infinite}.g2{animation:g2 5s steps(1) infinite}"
        "@keyframes g1{0%,90%,100%{opacity:0;transform:none}91%{opacity:.8;transform:translate(-4px,1px)}94%{opacity:.8;transform:translate(3px,-1px)}97%{opacity:0}}"
        "@keyframes g2{0%,91%,100%{opacity:0;transform:none}92%{opacity:.8;transform:translate(4px,-1px)}95%{opacity:.8;transform:translate(-3px,1px)}98%{opacity:0}}"
        ".scan{animation:scan 6s linear infinite}@keyframes scan{0%{transform:translateY(0)}100%{transform:translateY(356px)}}"
        ".cur{animation:blink 1s steps(1) infinite}@keyframes blink{50%{opacity:0}}"
    )
    defs = DOTS + (
        f'<linearGradient id="shift" gradientUnits="userSpaceOnUse" x1="0" y1="0" x2="620" y2="0" spreadMethod="repeat">'
        f'<stop offset="0" stop-color="{VIOLET}"/><stop offset=".33" stop-color="{CYAN}"/><stop offset=".66" stop-color="{PINK}"/><stop offset="1" stop-color="{VIOLET}"/>'
        f'<animateTransform attributeName="gradientTransform" type="translate" from="0 0" to="620 0" dur="6s" repeatCount="indefinite"/></linearGradient>'
        f'<linearGradient id="scanG" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{CYAN}" stop-opacity="0"/><stop offset="1" stop-color="{CYAN}" stop-opacity=".18"/></linearGradient>'
        f'<clipPath id="heroClip"><rect x="1" y="1" width="{w-2}" height="{h-2}" rx="18"/></clipPath>')
    body = (
        panel(w, h) + chrome("ruban@agent-os: ~/profile — zsh")
        + f'<g clip-path="url(#heroClip)">{edges}{pts}<rect class="scan" x="0" y="-40" width="{w}" height="40" fill="url(#scanG)"/></g>'
        + f'<text x="60" y="104" class="m" font-size="13" letter-spacing="4" fill="{MUTED}">AI ENGINEER · AGENTIC SYSTEMS · MCP</text>'
        + f'<text x="58" y="172" font-size="60" font-weight="800" letter-spacing="1" fill="{CYAN}" class="g1">{name}</text>'
        + f'<text x="58" y="172" font-size="60" font-weight="800" letter-spacing="1" fill="{PINK}" class="g2">{name}</text>'
        + f'<text x="58" y="172" font-size="60" font-weight="800" letter-spacing="1" fill="url(#shift)">{name}</text>'
        + f'<text x="60" y="232" class="m" font-size="20" fill="{MUTED}">$ building</text>' + role_txt
        + chips
    )
    write("hero.svg", svg(w, h, body, css, defs))


def boot():
    lines = [
        ("cmd", "./boot --profile --verbose"),
        ("ok", "mounting memory", "episodic · semantic · OWL/RDF ontology"),
        ("ok", "arming guardrails", "read-only SQL · egress allow-list · sandbox"),
        ("ok", "spawning swarm", "planner · researcher · coder · critic"),
        ("ok", "connecting MCP servers", "plant data → Claude (read-only)"),
        ("ok", "calibrating confidence", "faithfulness gate on every write"),
        ("ok", "loading eval harness", "no-regression · human-approved changes"),
        ("hot", "data plane", "IND · BAN · SL · JOR — online"),
    ]
    w, top, step, loop = 1000, 74, 30, 18.0
    h = top + (len(lines) + 1) * step + 20
    css, body = [], [panel(w, h), chrome("ruban@agent-os: ~ — boot.log")]
    prompt = (f'<tspan fill="{GREEN}">ruban@agent-os</tspan><tspan fill="{VIOLET}">:~$ </tspan>')
    for i, ln in enumerate(lines):
        y = top + i * step + 14
        p = (0.4 + i * 0.75) / loop * 100
        css.append(f".l{i}{{opacity:0;animation:l{i} {loop}s infinite}}"
                   f"@keyframes l{i}{{0%,{p:.1f}%{{opacity:0}}{p+0.6:.1f}%,96%{{opacity:1}}100%{{opacity:0}}}}")
        if ln[0] == "cmd":
            tw = len(ln[1]) * CH
            body.append(
                f'<clipPath id="type"><rect x="{40+18*CH}" y="{y-16}" height="24" width="0">'
                f'<animate attributeName="width" values="0;0;{tw:.0f};{tw:.0f};0" keyTimes="0;.03;.1;.96;1" dur="{loop}s" repeatCount="indefinite"/></rect></clipPath>'
                f'<text x="40" y="{y}" class="m" font-size="14" fill="{TEXT}">{prompt}</text>'
                f'<text x="{40+18*CH}" y="{y}" class="m" font-size="14" fill="{TEXT}" clip-path="url(#type)">{esc(ln[1])}</text>')
            continue
        tag, col = ("[  OK  ]", GREEN) if ln[0] == "ok" else ("[ LIVE ]", AMBER)
        dots = "." * max(3, 26 - len(ln[1]))
        body.append(
            f'<text x="40" y="{y}" class="m l{i}" font-size="14"><tspan fill="{col}">{tag}</tspan>'
            f'<tspan fill="{TEXT}"> {esc(ln[1])} </tspan><tspan fill="{MUTED}" fill-opacity=".35">{dots}</tspan>'
            f'<tspan fill="{CYAN}"> {esc(ln[2])}</tspan></text>')
    y = top + len(lines) * step + 14
    p = (0.4 + len(lines) * 0.75) / loop * 100
    css.append(f".lz{{opacity:0;animation:lz {loop}s infinite}}"
               f"@keyframes lz{{0%,{p:.1f}%{{opacity:0}}{p+0.6:.1f}%,96%{{opacity:1}}100%{{opacity:0}}}}"
               ".cur{animation:blink 1s steps(1) infinite}@keyframes blink{50%{opacity:0}}")
    last = 'echo "welcome — scroll down"'
    body.append(f'<g class="lz"><text x="40" y="{y}" class="m" font-size="14">{prompt}'
                f'<tspan fill="{TEXT}">{esc(last)}</tspan></text>'
                f'<rect class="cur" x="{40+(18+len(last)+0.5)*CH:.0f}" y="{y-13}" width="9" height="17" fill="{CYAN}"/></g>')
    write("boot.svg", svg(w, h, "".join(body), "".join(css), DOTS))


def swarm():
    w, h, cx, cy, r = 1000, 450, 500, 236, 150
    agents = [("PLANNER", VIOLET), ("RESEARCHER", CYAN), ("CODER", PINK),
              ("CRITIC", AMBER), ("MEMORY", GREEN), ("GUARDRAIL", "#F87171")]
    pos = [(cx + r * math.cos(math.radians(-90 + i * 60)), cy + r * math.sin(math.radians(-90 + i * 60)))
           for i in range(len(agents))]
    body = [panel(w, h), chrome("aura · swarm-executor · live")]
    body.append(f'<g opacity=".55"><circle cx="{cx}" cy="{cy}" r="{r}" stroke="{VIOLET}" stroke-dasharray="3 9">'
                f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="40s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{cx}" cy="{cy}" r="{r+48}" stroke="{CYAN}" stroke-opacity=".4" stroke-dasharray="1 14">'
                f'<animateTransform attributeName="transform" type="rotate" from="360 {cx} {cy}" to="0 {cx} {cy}" dur="60s" repeatCount="indefinite"/></circle></g>')
    for i, ((x, y), (name, col)) in enumerate(zip(pos, agents)):
        d = f"M{cx},{cy} L{x:.1f},{y:.1f}"
        body.append(f'<path d="{d}" stroke="{col}" stroke-opacity=".35"/>')
        for k, (kp, dur) in enumerate([("0;1", 2.2 + i * .35), ("1;0", 3.1 + i * .25)]):
            body.append(f'<circle r="{3.5 if k == 0 else 2.5}" fill="{col}" filter="url(#glow)">'
                        f'<animateMotion dur="{dur:.2f}s" repeatCount="indefinite" path="{d}" keyPoints="{kp}" keyTimes="0;1" calcMode="linear"/></circle>')
    for (x, y), (name, col) in zip(pos, agents):
        bw = len(name) * 8.6 + 34
        body.append(f'<rect x="{x-bw/2:.1f}" y="{y-17:.1f}" width="{bw:.1f}" height="34" rx="10" fill="{PANEL}" stroke="{col}"/>'
                    f'<circle cx="{x-bw/2+14:.1f}" cy="{y:.1f}" r="3.5" fill="{col}"><animate attributeName="opacity" values="1;.2;1" dur="1.6s" repeatCount="indefinite"/></circle>'
                    f'<text x="{x-bw/2+24:.1f}" y="{y+4.5:.1f}" class="m" font-size="13" font-weight="600" fill="{TEXT}">{name}</text>')
    body.append(f'<circle cx="{cx}" cy="{cy}" r="46" fill="{VIOLET}" fill-opacity=".15" stroke="{VIOLET}">'
                f'<animate attributeName="r" values="46;64;46" dur="3s" repeatCount="indefinite"/>'
                f'<animate attributeName="stroke-opacity" values=".9;0;.9" dur="3s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{cx}" cy="{cy}" r="46" fill="{PANEL}" stroke="url(#brand)" stroke-width="2" filter="url(#glow)"/>'
                f'<text x="{cx}" y="{cy+2}" text-anchor="middle" font-size="22" font-weight="800" fill="url(#brand)">AURA</text>'
                f'<text x="{cx}" y="{cy+19}" text-anchor="middle" class="m" font-size="9" fill="{MUTED}">orchestrator</text>')

    def column(x, title, items, col):
        out = f'<text x="{x}" y="96" class="m" font-size="12" letter-spacing="3" fill="{col}">{title}</text>'
        for j, it in enumerate(items):
            out += (f'<text x="{x}" y="{128+j*30}" class="m" font-size="13" fill="{TEXT}">'
                    f'<tspan fill="{col}">▸ </tspan>{esc(it)}</text>')
        return out
    body.append(column(40, "TOPOLOGIES", ["hierarchical", "pipeline", "debate", "market", "+ swarm skills"], CYAN))
    body.append(column(745, "GUARANTEES", ["fail-closed tool scope", "eval-gated self-edits", "human approval on writes",
                                           "tamper → quarantine", "blast-radius replay"], PINK))
    body.append(f'<text x="{cx}" y="{h-22}" text-anchor="middle" class="m" font-size="11" fill="{MUTED}">'
                f'packets = messages between agents · every arrow is a tool call that passed a guardrail</text>')
    write("swarm.svg", svg(w, h, "".join(body), "", DOTS))


def stack():
    w, h, cx, cy = 1000, 540, 500, 280
    orbits = [(95, 34, ["Python", "MCP", "Multi-Agent"], VIOLET),
              (168, -52, ["TypeScript", "React", "Vite", "Flutter", "Dart"], CYAN),
              (240, 70, ["SQL Server", "SQLite", "PostgreSQL", "MongoDB", "Node.js", "GitHub Actions", "rdflib"], PINK)]
    body = [panel(w, h), chrome("stack.orbit() — gravity: Claude")]
    for r, dur, items, col in orbits:
        body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{col}" stroke-opacity=".25" stroke-dasharray="2 6"/>')
        frm, to = (0, 360) if dur > 0 else (360, 0)
        g = (f'<g><animateTransform attributeName="transform" type="rotate" from="{frm} {cx} {cy}" '
             f'to="{to} {cx} {cy}" dur="{abs(dur)}s" repeatCount="indefinite"/>')
        for k, it in enumerate(items):
            a = 2 * math.pi * k / len(items)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            cw = len(it) * 7.6 + 24
            g += (f'<g transform="translate({x:.1f} {y:.1f})"><g>'
                  f'<animateTransform attributeName="transform" type="rotate" from="{-frm}" to="{-to}" dur="{abs(dur)}s" repeatCount="indefinite"/>'
                  f'<rect x="{-cw/2:.1f}" y="-14" width="{cw:.1f}" height="28" rx="14" fill="{PANEL}" stroke="{col}"/>'
                  f'<text x="0" y="4.5" text-anchor="middle" class="m" font-size="12.5" fill="{TEXT}">{esc(it)}</text></g></g>')
        body.append(g + "</g>")
    body.append(f'<circle cx="{cx}" cy="{cy}" r="40" fill="#D97757" fill-opacity=".18" stroke="#D97757" filter="url(#glow)">'
                f'<animate attributeName="r" values="38;44;38" dur="4s" repeatCount="indefinite"/></circle>'
                f'<text x="{cx}" y="{cy+6}" text-anchor="middle" font-size="17" font-weight="800" fill="#F0A58A">Claude</text>')
    for i, (lbl, col) in enumerate([("inner · AI core", VIOLET), ("middle · apps & UI", CYAN), ("outer · data & infra", PINK)]):
        body.append(f'<circle cx="44" cy="{h-80+i*24}" r="5" fill="{col}"/>'
                    f'<text x="58" y="{h-75.5+i*24}" class="m" font-size="12" fill="{MUTED}">{esc(lbl)}</text>')
    write("stack.svg", svg(w, h, "".join(body), "", DOTS))


def project_cards():
    w, h = 490, 268
    per = 2 * (w - 2 + h - 2)
    for p in PROJECTS:
        col = p["accent"]
        css = (f".run{{stroke-dasharray:160 {per-160};animation:run 7s linear infinite}}"
               f"@keyframes run{{to{{stroke-dashoffset:-{per}}}}}")
        body = [panel(w, h),
                f'<rect class="run" x="1" y="1" width="{w-2}" height="{h-2}" rx="18" stroke="{col}" stroke-width="2" filter="url(#glow)"/>',
                f'<polygon points="44,30 58,38 58,54 44,62 30,54 30,38" fill="{col}" fill-opacity=".15" stroke="{col}"/>'
                f'<circle cx="44" cy="46" r="4" fill="{col}"><animate attributeName="r" values="3;6;3" dur="2s" repeatCount="indefinite"/></circle>',
                f'<text x="74" y="46" font-size="22" font-weight="800" fill="{TEXT}">{esc(p["name"])}</text>',
                f'<text x="74" y="66" class="m" font-size="11.5" fill="{col}">{esc(p["tag"])}</text>']
        for j, b in enumerate(p["bullets"]):
            body.append(f'<text x="30" y="{104+j*27}" font-size="13.5" fill="{TEXT}"><tspan fill="{col}">▸ </tspan>{esc(b)}</text>')
        x = 30
        for c in p["chips"]:
            cw = len(c) * 7.2 + 20
            body.append(f'<rect x="{x}" y="{h-50}" width="{cw:.0f}" height="24" rx="12" fill="{col}" fill-opacity=".1" stroke="{col}" stroke-opacity=".45"/>'
                        f'<text x="{x+10}" y="{h-33.5}" class="m" font-size="11.5" fill="{col}">{esc(c)}</text>')
            x += cw + 8
        write(f"card-{p['slug']}.svg", svg(w, h, "".join(body), css, DOTS))


def concept(today):
    name, idea, arxiv = AGENT_PATTERNS[today.toordinal() % len(AGENT_PATTERNS)]
    w, h = 1000, 170
    css = ".bar{animation:grow 3s ease-out infinite alternate}@keyframes grow{from{transform:scaleX(.15)}to{transform:scaleX(1)}}"
    body = (panel(w, h)
            + f'<text x="40" y="44" class="m" font-size="12" letter-spacing="3" fill="{AMBER}">◆ AGENT PATTERN OF THE DAY · {today:%d %b %Y}</text>'
            + f'<text x="40" y="88" font-size="30" font-weight="800" fill="url(#brand)">{esc(name)}</text>'
            + f'<text x="40" y="120" font-size="15" fill="{TEXT}">{esc(idea)}</text>'
            + f'<rect x="40" y="138" width="200" height="3" rx="1.5" fill="url(#brand)" class="bar" style="transform-origin:40px 0"/>'
            + f'<rect x="{w-170}" y="26" width="132" height="28" rx="14" fill="{AMBER}" fill-opacity=".1" stroke="{AMBER}" stroke-opacity=".5"/>'
            + f'<text x="{w-104}" y="45" text-anchor="middle" class="m" font-size="12" fill="{AMBER}">arXiv:{arxiv}</text>')
    write("concept.svg", svg(w, h, body, css, DOTS))


def divider():
    w, h = 1000, 30
    body = (f'<defs><linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="{VIOLET}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{CYAN}"/><stop offset="1" stop-color="{PINK}" stop-opacity="0"/></linearGradient></defs>'
            f'<line x1="0" y1="15" x2="{w}" y2="15" stroke="url(#fade)" stroke-width="1.5"/>'
            f'<circle r="4" cy="15" fill="{CYAN}" filter="url(#glow)"><animate attributeName="cx" values="60;940;60" dur="8s" repeatCount="indefinite"/></circle>')
    write("divider.svg", svg(w, h, body))


def footer(now):
    w, h = 1000, 150
    wave = "M0,110 " + " ".join(f"Q{x+25},{90 if (x // 50) % 2 == 0 else 130} {x+50},110" for x in range(0, 1050, 50))
    css = (".wave{stroke-dasharray:12 10;animation:flow 3s linear infinite}@keyframes flow{to{stroke-dashoffset:-44}}"
           ".cur{animation:blink 1s steps(1) infinite}@keyframes blink{50%{opacity:0}}")
    body = (f'<path class="wave" d="{wave}" stroke="url(#brand)" stroke-width="2" opacity=".7"/>'
            + f'<text x="{w/2}" y="46" text-anchor="middle" class="m" font-size="15" fill="{TEXT}">'
              f'<tspan fill="{GREEN}">ruban@agent-os</tspan><tspan fill="{VIOLET}">:~$ </tspan>exit</text>'
            + f'<text x="{w/2}" y="72" text-anchor="middle" class="m" font-size="12" fill="{MUTED}">'
              f'session closed · thanks for stopping by · re-rendered {now:%Y-%m-%d %H:%M} UTC</text>'
            + f'<rect class="cur" x="{w/2+52}" y="33" width="9" height="16" fill="{CYAN}"/>')
    write("footer.svg", svg(w, h, body, css))


# ── live data ────────────────────────────────────────────────────────────────
def fetch(url, api=False):
    hdr = {"User-Agent": f"{USER}-profile-renderer"}
    if api:
        hdr["Accept"] = "application/vnd.github+json"
        if TOKEN:
            hdr["Authorization"] = f"Bearer {TOKEN}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=hdr), timeout=30) as r:
        return r.read().decode("utf-8")


def contributions():
    """Day-by-day calendar from the public contributions page: [(date, count, level)], total."""
    page = fetch(f"https://github.com/users/{USER}/contributions")
    tips = {}
    for tid, text in re.findall(r'<tool-tip[^>]*\bfor="([^"]+)"[^>]*>([^<]*)</tool-tip>', page):
        m = re.match(r"\s*([\d,]+) contribution", text)
        tips[tid] = int(m.group(1).replace(",", "")) if m else 0
    days = []
    for tag in re.findall(r"<td\b[^>]*\bdata-date=[^>]*>", page):
        a = dict(re.findall(r'([\w-]+)="([^"]*)"', tag))
        days.append((dt.date.fromisoformat(a["data-date"]), tips.get(a.get("id"), 0), int(a.get("data-level", 0))))
    days.sort()
    m = re.search(r"([\d,]+)\s+contributions?\s+in the last year", page)
    total = int(m.group(1).replace(",", "")) if m else sum(c for _, c, _ in days)
    if not days:
        raise ValueError("no calendar cells found")
    return days, total


def streaks(days, today):
    longest = run = 0
    for _, c, _ in days:
        run = run + 1 if c else 0
        longest = max(longest, run)
    cur = 0
    for d, c, _ in reversed(days):
        if d > today:
            continue
        if c:
            cur += 1
        elif d < today:  # an empty today doesn't break the streak yet
            break
    return cur, longest


def heatmap(days, total):
    w, h, x0, y0, s = 1000, 250, 70, 70, 16
    start = days[0][0] - dt.timedelta(days=(days[0][0].weekday() + 1) % 7)
    css = (".c{opacity:0;animation:pop 24s infinite;transform-box:fill-box;transform-origin:center}"
           "@keyframes pop{0%{opacity:0;transform:scale(.2)}3%{opacity:1;transform:scale(1)}94%{opacity:1;transform:scale(1)}100%{opacity:0;transform:scale(.2)}}")
    body = [panel(w, h),
            f'<text x="40" y="42" class="m" font-size="12" letter-spacing="3" fill="{CYAN}">CONTRIBUTIONS · LAST 12 MONTHS</text>',
            f'<text x="{w-40}" y="42" text-anchor="end" font-size="15" font-weight="700" fill="{TEXT}">{total:,} contributions</text>']
    seen = set()
    for d, c, lvl in days:
        col, row = (d - start).days // 7, (d.weekday() + 1) % 7
        x, y = x0 + col * s, y0 + row * s
        body.append(f'<rect class="c" x="{x}" y="{y}" width="12" height="12" rx="3" fill="{HEAT[min(lvl, 4)]}" '
                    f'style="animation-delay:{col*45}ms"><title>{c} on {d:%d %b %Y}</title></rect>')
        if d.day <= 7 and row == 0 and (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            body.append(f'<text x="{x}" y="{y0-10}" class="m" font-size="10.5" fill="{MUTED}">{d:%b}</text>')
    for row, lbl in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        body.append(f'<text x="38" y="{y0+row*s+10}" class="m" font-size="10" fill="{MUTED}">{lbl}</text>')
    lx = w - 40 - 5 * 16 - 70
    body.append(f'<text x="{lx}" y="{h-22}" class="m" font-size="10.5" fill="{MUTED}">less</text>')
    body += [f'<rect x="{lx+34+i*16}" y="{h-32}" width="12" height="12" rx="3" fill="{c}"/>' for i, c in enumerate(HEAT)]
    body.append(f'<text x="{lx+34+5*16+4}" y="{h-22}" class="m" font-size="10.5" fill="{MUTED}">more</text>')
    write("heatmap.svg", svg(w, h, "".join(body), css, DOTS))


def stats_card(days, total, today):
    cur, longest = streaks(days, today)
    active = sum(1 for _, c, _ in days if c)
    best_d, best_c, _ = max(days, key=lambda t: t[1])
    try:
        repos = [r for r in json.loads(fetch(f"https://api.github.com/users/{USER}/repos?per_page=100&type=owner", api=True))
                 if not r.get("fork")]
    except Exception as e:  # noqa: BLE001 — the calendar half of the card is still worth drawing
        print(f"  repos fetch failed: {e}")
        repos = None
    w, h = 1000, 260
    tiles = [(f"{total:,}", "contributions / yr", VIOLET), (f"{cur} d", "current streak", CYAN),
             (f"{longest} d", "longest streak", PINK), (f"{active}", "active days", GREEN),
             (str(len(repos)) if repos is not None else "—", "public repos", AMBER)]
    css = ".ring{animation:ring 2.4s ease-out both}@keyframes ring{from{stroke-dashoffset:126}}"
    body = [panel(w, h), f'<text x="40" y="42" class="m" font-size="12" letter-spacing="3" fill="{PINK}">TELEMETRY</text>',
            f'<text x="{w-40}" y="42" text-anchor="end" class="m" font-size="11" fill="{MUTED}">best day: {best_c} on {best_d:%d %b %Y}</text>']
    tw = (w - 80) / len(tiles)
    for i, (val, lbl, col) in enumerate(tiles):
        x = 40 + i * tw
        body.append(f'<rect x="{x+4:.0f}" y="62" width="{tw-8:.0f}" height="96" rx="14" fill="{col}" fill-opacity=".06" stroke="{col}" stroke-opacity=".35"/>'
                    f'<circle cx="{x+34:.0f}" cy="110" r="20" stroke="{LINE}" stroke-width="4"/>'
                    f'<circle class="ring" cx="{x+34:.0f}" cy="110" r="20" stroke="{col}" stroke-width="4" stroke-linecap="round" '
                    f'stroke-dasharray="126" stroke-dashoffset="{126*(1-0.25-0.15*i):.0f}" transform="rotate(-90 {x+34:.0f} 110)" style="animation-delay:{i*.2}s"/>'
                    f'<text x="{x+66:.0f}" y="112" font-size="25" font-weight="800" fill="{TEXT}">{esc(val)}</text>'
                    f'<text x="{x+66:.0f}" y="134" class="m" font-size="11" fill="{MUTED}">{esc(lbl)}</text>')
    if repos:
        langs = Counter(r["language"] for r in repos if r.get("language")).most_common(6)
        n = sum(c for _, c in langs) or 1
        palette = [VIOLET, CYAN, PINK, GREEN, AMBER, "#60A5FA"]
        body.append(f'<text x="40" y="188" class="m" font-size="11" fill="{MUTED}">languages · by public repo count</text>')
        x = 40.0
        for i, (lang, c) in enumerate(langs):
            seg = (w - 80) * c / n
            body.append(f'<rect x="{x:.1f}" y="198" width="0" height="10" fill="{palette[i]}">'
                        f'<animate attributeName="width" from="0" to="{max(seg-2, 2):.1f}" dur="1.2s" begin="{i*.15:.2f}s" fill="freeze"/></rect>'
                        f'<circle cx="{40+i*150+5}" cy="231" r="4.5" fill="{palette[i]}"/>'
                        f'<text x="{40+i*150+15}" y="235" class="m" font-size="11.5" fill="{TEXT}">{esc(lang)} <tspan fill="{MUTED}">{100*c/n:.0f}%</tspan></text>')
            x += seg
    write("stats.svg", svg(w, h, "".join(body), css, DOTS))


def activity():
    events = json.loads(fetch(f"https://api.github.com/users/{USER}/events/public?per_page=40", api=True))
    out = []
    for e in events:
        repo, pl, when = e["repo"]["name"], e.get("payload", {}), e["created_at"][:10]
        link = f"[{repo.split('/')[-1]}](https://github.com/{repo})"
        t = e["type"]
        if t == "PushEvent":
            n = pl.get("size") or len(pl.get("commits", []))
            line = f"⚡ pushed {n} commit{'s' if n != 1 else ''} to {link}" if n else f"⚡ pushed to {link}"
        elif t == "CreateEvent":
            line = f"🌱 created {pl.get('ref_type', 'ref')} `{pl.get('ref') or repo.split('/')[-1]}` in {link}"
        elif t == "PullRequestEvent":
            line = f"🔀 {pl.get('action')} PR #{pl.get('number')} in {link}"
        elif t == "ReleaseEvent":
            line = f"🚀 released `{pl.get('release', {}).get('tag_name', '')}` in {link}"
        elif t == "WatchEvent":
            line = f"⭐ starred {link}"
        elif t == "IssuesEvent":
            line = f"🐛 {pl.get('action')} issue #{pl.get('issue', {}).get('number')} in {link}"
        else:
            continue
        entry = f"- `{when}` {line}"
        if entry not in out:
            out.append(entry)
        if len(out) == 6:
            break
    return "\n".join(out) or "- _quiet on the public side — most of the work lives in private repos_"


def splice(text, key, content):
    return re.sub(rf"(<!--{key}:START-->).*?(<!--{key}:END-->)", lambda m: f"{m.group(1)}\n{content}\n{m.group(2)}",
                  text, flags=re.S)


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.date()
    for f in (hero, boot, swarm, stack, project_cards, divider):
        f()
    concept(today)
    footer(now)
    try:
        days, total = contributions()
        heatmap(days, total)
        stats_card(days, total, today)
    except Exception as e:  # noqa: BLE001 — keep yesterday's charts rather than drawing empty ones
        print(f"  contributions fetch failed, keeping existing heatmap/stats: {e}")
    try:
        README.write_text(splice(README.read_text(encoding="utf-8"), "ACTIVITY", activity()), encoding="utf-8")
        print("  refreshed README activity block")
    except Exception as e:  # noqa: BLE001
        print(f"  activity fetch failed, README left unchanged: {e}")


if __name__ == "__main__":
    main()
