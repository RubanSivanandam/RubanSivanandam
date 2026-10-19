#!/usr/bin/env python3
"""Render every self-hosted SVG on the profile and refresh the README's live block.

Stdlib only. Run by .github/workflows/profile.yml every 6 hours; runs locally too:
    python scripts/render.py
Live data (contribution calendar, repos, public events) is fetched from GitHub. If a
fetch fails, the SVGs that depend on it are left as they are rather than drawn empty.

The look is monochrome luxe: black and warm white, one gold accent, a didone for display
type, and motion that eases in once on load and then only breathes.
"""
import datetime as dt
import html
import json
import math
import os
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

# ── design tokens: monochrome luxe ───────────────────────────────────────────
INK, LINE, RULE = "#0A0A0A", "#1E1E1E", "#2C2C2C"
TEXT, SOFT, MUTED, DIM = "#F5F3EE", "#C9C5BC", "#8C8A85", "#55524E"
GOLD, GOLD_DIM = "#C9A24B", "#6B5A33"
HEAT = ["#171717", "#2E2A22", "#5C4D2A", "#9A7C36", "#C9A24B"]
SERIF = "'Bodoni Moda','Bodoni 72','Didot','Bodoni MT','Playfair Display',Georgia,serif"
SANS = "'Archivo','Helvetica Neue',Helvetica,Arial,sans-serif"
MONO = "'JetBrains Mono','SFMono-Regular',Consolas,Menlo,monospace"
EASE = "cubic-bezier(.2,.8,.2,1)"

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

AURA_REPO = "Agentic-Unified-Reasoning-Architecture"  # source is private; its README + CHANGELOG are public

BUILDS = [  # private repos — (name, tagline, what it does, chips)
    ("Claude Code Harness", "portable · guarded · self-testing",
     ["One clone restores the same skills, hooks, mods and MCP servers on any machine",
      "Deny-by-default .gitignore: credentials and transcripts never travel",
      "Every third-party mod pinned to a reviewed commit SHA",
      "Daily scout triages new skills, plugins and papers: adopt · trial · skip"],
     ["Python", "Hooks", "MCP", "CI"]),
    ("AI Tutor", "AI-OS · a harness that teaches, not does",
     ["Hint-first mentor; a hook refuses to write the learner's exercises",
      "FSRS-6 spaced repetition brings weak spots back on schedule",
      "Reviewer, red-teamer and interviewer agents with no write tools",
      "Learning-tracker MCP server on a zero-dependency engine"],
     ["Python", "Claude Code", "MCP", "FSRS"]),
    ("Creators Agentic AI", "Showrunner · revenue, not views",
     ["An AI organisation for creators: agents with roles, memory and KPIs",
      "Daily run: trends → competitors → revenue → a decision you approve",
      "Ideas ranked by expected return, priced on the creator's real RPM",
      "Self-hosted, runs with zero API keys; approval gates on by default"],
     ["Python", "Next.js", "Celery", "Docker"]),
]


def esc(s):
    return html.escape(str(s), quote=True)


def svg(w, h, body, css="", defs=""):
    """One panel. Shared motion: .rise (lifts in), .fade, .draw (a line drawn left to right),
    each eased once on load; stagger with style="animation-delay:…"."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" fill="none">'
        f"<style>text{{font-family:{SANS}}}.s{{font-family:{SERIF}}}.m{{font-family:{MONO}}}"
        f".rise{{animation:rise 1.1s {EASE} both}}@keyframes rise{{from{{opacity:0;transform:translateY(16px)}}}}"
        f".fade{{animation:fade 1.4s {EASE} both}}@keyframes fade{{from{{opacity:0}}}}"
        f".draw{{animation:draw 1.6s {EASE} both;transform-box:fill-box;transform-origin:0 50%}}@keyframes draw{{from{{transform:scaleX(0)}}}}"
        f".breathe{{animation:breathe 4s ease-in-out infinite;transform-box:fill-box;transform-origin:center}}"
        f"@keyframes breathe{{50%{{transform:rotate(45deg) scale(1.35);opacity:.65}}}}{css}</style>"
        f"<defs>{defs}</defs>{body}</svg>"
    )


def card(w, h):
    """Black card, hairline edge, and an inner frame: the luxe border."""
    return (f'<rect x=".5" y=".5" width="{w-1}" height="{h-1}" rx="6" fill="{INK}" stroke="{LINE}"/>'
            f'<rect x="14.5" y="14.5" width="{w-29}" height="{h-29}" rx="2" stroke="{RULE}" stroke-opacity=".55"/>')


def label(x, y, text, col=MUTED, anchor="start", size=11, cls="fade", delay=0.0):
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" class="m {cls}" font-size="{size}" letter-spacing="3.4" '
            f'fill="{col}" style="animation-delay:{delay:.2f}s">{esc(text.upper())}</text>')


def diamond(cx, cy, s=7, col=GOLD, cls="", delay=0.0):
    return (f'<rect class="{cls}" x="{cx-s/2:.1f}" y="{cy-s/2:.1f}" width="{s}" height="{s}" fill="{col}" '
            f'transform="rotate(45 {cx:.1f} {cy:.1f})" style="animation-delay:{delay:.2f}s"/>')


def rule(x1, y, x2, col=RULE, delay=0.0, cls="draw"):
    return f'<line class="{cls}" x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{col}" style="animation-delay:{delay:.2f}s"/>'


def write(name, content):
    ET.fromstring(content)  # GitHub shows nothing for malformed XML; fail the run instead
    ASSETS.mkdir(exist_ok=True)
    (ASSETS / name).write_text(content, encoding="utf-8")
    print(f"  wrote assets/{name} ({len(content):,} bytes)")


# ── static panels ────────────────────────────────────────────────────────────
def hero():
    """The name in a didone, rising out of two masks; a gold hairline draws under it; the role
    turns over in gold; a monogram ring with the practice written round it turns slowly."""
    w, h = 1000, 440
    roles = ["agentic systems", "Claude Code harnesses", "MCP servers", "zero-trust guardrails"]
    css = (f".mask1{{animation:up 1.3s {EASE} both .15s}}.mask2{{animation:up 1.3s {EASE} both .35s}}"
           "@keyframes up{from{transform:translateY(130px)}}"
           ".role{opacity:0;animation:role 16s infinite}"
           "@keyframes role{0%{opacity:0;transform:translateY(8px)}3%,22%{opacity:1;transform:translateY(0)}25%,100%{opacity:0;transform:translateY(-8px)}}")
    cx, cy, r = 838, 214, 104
    ring = f"M{cx},{cy} m-{r+22},0 a{r+22},{r+22} 0 1,1 {2*(r+22)},0 a{r+22},{r+22} 0 1,1 -{2*(r+22)},0"
    defs = (f'<clipPath id="l1"><rect x="40" y="96" width="740" height="126"/></clipPath>'
            f'<clipPath id="l2"><rect x="40" y="222" width="740" height="118"/></clipPath>'
            f'<path id="ringP" d="{ring}"/>')
    body = [card(w, h),
            label(56, 62, "AI engineer", MUTED, delay=.2), label(w - 56, 62, "UTC+05:30", MUTED, "end", delay=.3),
            f'<g clip-path="url(#l1)"><text x="60" y="198" class="s mask1" font-size="112" font-weight="700" fill="{TEXT}">Ruban</text></g>',
            f'<g clip-path="url(#l2)"><text x="60" y="310" class="s mask2" font-size="112" font-weight="700" fill="{TEXT}">Sivanandam</text></g>',
            rule(62, 338, 690, GOLD, .9), diamond(690, 338, 9, GOLD, "fade", 2.2),
            f'<text x="62" y="378" class="m fade" font-size="13" letter-spacing="3" fill="{MUTED}" style="animation-delay:1.2s">BUILDING —</text>']
    body += [f'<text x="196" y="378" class="m role" font-size="13" letter-spacing="3" fill="{GOLD}" '
             f'style="animation-delay:{1.4 + i*4:.1f}s">{esc(r_.upper())}</text>' for i, r_ in enumerate(roles)]
    meta = "AURA · AI TUTOR · SHOWRUNNER     |     CLAUDE · MCP · PYTHON · FLUTTER"
    body.append(f'<text x="62" y="412" xml:space="preserve" class="m fade" font-size="10.5" letter-spacing="2.4" fill="{DIM}" style="animation-delay:1.6s">{esc(meta)}</text>')
    # the monogram: a hairline circle, initials, the practice written round it, one gold point orbiting
    body.append(f'<g class="fade" style="animation-delay:.8s">'
                f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{RULE}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="{r-10}" stroke="{LINE}"/>'
                f'<text x="{cx}" y="{cy+22}" text-anchor="middle" class="s" font-size="62" fill="{TEXT}">RS</text>'
                f'<g><animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="60s" repeatCount="indefinite"/>'
                f'<text class="m" font-size="10.5" letter-spacing="4.2" fill="{MUTED}"><textPath href="#ringP">'
                f'AGENTIC SYSTEMS · CLAUDE CODE · MCP · GUARDRAILS · EVALS · </textPath></text></g>'
                f'<rect x="-3.5" y="-3.5" width="7" height="7" fill="{GOLD}" transform="rotate(45)">'
                f'<animateMotion dur="14s" repeatCount="indefinite" rotate="0" path="M{cx},{cy - r} a{r},{r} 0 1,1 -0.01,0"/></rect></g>')
    write("hero.svg", svg(w, h, "".join(body), css, defs))


def about():
    w, h = 1000, 300
    lines = ["Build agents whose work", "you can check, behind", "guardrails they can’t talk past."]
    body = [card(w, h), label(56, 62, "About", GOLD), rule(120, 58, 300, RULE, .3)]
    body += [f'<text x="56" y="{126 + i*50}" class="s rise" font-size="36" fill="{TEXT}" style="animation-delay:{.25 + i*.14:.2f}s">{esc(t)}</text>'
             for i, t in enumerate(lines)]
    body.append(f'<line x1="640" y1="48" x2="640" y2="{h-48}" stroke="{RULE}" class="fade" style="animation-delay:.4s"/>')
    facts = [("Role", ["AI Engineer", "agentic systems · Claude Code · MCP"]),
             ("Focus", ["multi-agent orchestration, RAG,", "LLM evaluation, AI security"]),
             ("Learning", ["in public: one agentic-AI", "concept a day on LinkedIn"])]
    for i, (k, vals) in enumerate(facts):
        y = 70 + i * 74
        body.append(label(672, y, k, MUTED, delay=.5 + i * .15))
        body += [f'<text x="672" y="{y + 22 + j*20}" class="rise" font-size="14.5" fill="{TEXT if j == 0 else SOFT}" '
                 f'style="animation-delay:{.6 + i*.15:.2f}s">{esc(v)}</text>' for j, v in enumerate(vals)]
    write("about.svg", svg(w, h, "".join(body)))


def builds():
    """One row per private build: a gold number, the name in the didone, its line, its stack;
    what it does on the right. Rows lift in one after another; their rules draw across."""
    w, top, rh = 1000, 92, 158
    h = top + len(BUILDS) * rh + 30
    body = [card(w, h), label(56, 62, "Selected builds", GOLD), label(w - 56, 62, "private repositories", MUTED, "end")]
    for i, (name, tag, lines, chips) in enumerate(BUILDS):
        y, d = top + i * rh, .2 + i * .22
        body.append(f'<g class="rise" style="animation-delay:{d:.2f}s">'
                    f'<text x="56" y="{y+34}" class="m" font-size="12" letter-spacing="2" fill="{GOLD}">{i+1:02d}</text>'
                    f'<text x="96" y="{y+40}" class="s" font-size="30" fill="{TEXT}">{esc(name)}</text>'
                    f'<text x="96" y="{y+66}" class="m" font-size="10.5" letter-spacing="2.4" fill="{MUTED}">{esc(tag.upper())}</text>'
                    f'<text x="96" y="{y+118}" class="m" font-size="10.5" letter-spacing="2.4" fill="{DIM}">{esc("  /  ".join(c.upper() for c in chips))}</text>')
        for j, ln in enumerate(lines):
            body.append(f'<rect x="452" y="{y+22+j*28}" width="5" height="5" fill="{GOLD_DIM}" transform="rotate(45 454.5 {y+24.5+j*28})"/>'
                        f'<text x="470" y="{y+30+j*28}" font-size="12.8" fill="{SOFT}">{esc(ln)}</text>')
        body.append("</g>")
        body.append(rule(56, y + rh - 8, w - 56, RULE, d + .3))
    write("builds.svg", svg(w, h, "".join(body)))


def swarm():
    w, h, cx, cy, r = 1000, 460, 500, 244, 150
    agents = ["PLANNER", "RESEARCHER", "CODER", "CRITIC", "MEMORY", "GUARDRAIL"]
    pos = [(cx + r * math.cos(math.radians(-90 + i * 60)), cy + r * math.sin(math.radians(-90 + i * 60))) for i in range(6)]
    body = [card(w, h), label(56, 62, "AURA · the swarm", GOLD), label(w - 56, 62, "live", MUTED, "end")]
    body.append(f'<g class="fade" style="animation-delay:.2s"><circle cx="{cx}" cy="{cy}" r="{r}" stroke="{RULE}" stroke-dasharray="2 8">'
                f'<animateTransform attributeName="transform" type="rotate" from="0 {cx} {cy}" to="360 {cx} {cy}" dur="90s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{cx}" cy="{cy}" r="{r+44}" stroke="{LINE}"/></g>')
    for i, ((x, y), name) in enumerate(zip(pos, agents)):
        d = f"M{cx},{cy} L{x:.1f},{y:.1f}"
        body.append(f'<path d="{d}" stroke="{RULE}" class="fade" style="animation-delay:{.3 + i*.08:.2f}s"/>')
        for k, (kp, dur) in enumerate([("0;1", 3.2 + i * .4), ("1;0", 4.4 + i * .3)]):
            body.append(f'<rect x="-2" y="-2" width="4" height="4" fill="{GOLD if k == 0 else SOFT}" transform="rotate(45)">'
                        f'<animateMotion dur="{dur:.2f}s" repeatCount="indefinite" path="{d}" keyPoints="{kp}" keyTimes="0;1" calcMode="linear"/></rect>')
    for i, ((x, y), name) in enumerate(zip(pos, agents)):
        bw = len(name) * 9.4 + 36
        body.append(f'<g class="rise" style="animation-delay:{.4 + i*.1:.2f}s">'
                    f'<rect x="{x-bw/2:.1f}" y="{y-16:.1f}" width="{bw:.1f}" height="32" fill="{INK}" stroke="{RULE}"/>'
                    f'<rect x="{x-bw/2+12:.1f}" y="{y-2.5:.1f}" width="5" height="5" fill="{GOLD}" transform="rotate(45 {x-bw/2+14.5:.1f} {y:.1f})"/>'
                    f'<text x="{x-bw/2+26:.1f}" y="{y+4.5:.1f}" class="m" font-size="12" letter-spacing="2" fill="{TEXT}">{name}</text></g>')
    body.append(f'<circle cx="{cx}" cy="{cy}" r="54" fill="{INK}" stroke="{GOLD}" stroke-opacity=".8"/>'
                f'<circle cx="{cx}" cy="{cy}" r="54" stroke="{GOLD}" stroke-opacity=".5">'
                f'<animate attributeName="r" values="54;72;54" dur="4s" repeatCount="indefinite"/>'
                f'<animate attributeName="stroke-opacity" values=".5;0;.5" dur="4s" repeatCount="indefinite"/></circle>'
                f'<text x="{cx}" y="{cy+6}" text-anchor="middle" class="s" font-size="26" fill="{TEXT}">AURA</text>'
                f'<text x="{cx}" y="{cy+24}" text-anchor="middle" class="m" font-size="8.5" letter-spacing="2" fill="{MUTED}">ORCHESTRATOR</text>')

    def column(x, title, items, anchor):
        out = label(x, 120, title, MUTED, anchor)
        for j, it in enumerate(items):
            out += (f'<text x="{x}" y="{152 + j*30}" text-anchor="{anchor}" class="rise" font-size="14" fill="{SOFT}" '
                     f'style="animation-delay:{.5 + j*.08:.2f}s">{esc(it)}</text>')
        return out
    body.append(column(56, "Topologies", ["hierarchical", "pipeline", "debate", "market", "swarm skills"], "start"))
    body.append(column(w - 56, "Guarantees", ["fail-closed tool scope", "eval-gated self-edits", "human approval on writes",
                                               "tamper → quarantine", "blast-radius replay"], "end"))
    body.append(f'<text x="{cx}" y="{h-30}" text-anchor="middle" class="m fade" font-size="10.5" letter-spacing="1.6" fill="{DIM}" style="animation-delay:1s">'
                f'EVERY PACKET IS A MESSAGE BETWEEN AGENTS · EVERY LINE A TOOL CALL THAT PASSED A GUARDRAIL</text>')
    write("swarm.svg", svg(w, h, "".join(body)))


def stack():
    w, h, cx, cy = 1000, 540, 500, 278
    orbits = [(96, 40, ["Python", "MCP", "Multi-Agent"], GOLD_DIM),
              (170, -60, ["TypeScript", "React", "Vite", "Flutter", "Dart"], RULE),
              (242, 80, ["SQL Server", "SQLite", "PostgreSQL", "MongoDB", "Node.js", "GitHub Actions", "rdflib"], RULE)]
    body = [card(w, h), label(56, 62, "Stack", GOLD), label(w - 56, 62, "gravity: Claude", MUTED, "end")]
    for r, dur, items, col in orbits:
        body.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" stroke="{LINE}"/>')
        frm, to = (0, 360) if dur > 0 else (360, 0)
        g = (f'<g class="fade"><animateTransform attributeName="transform" type="rotate" from="{frm} {cx} {cy}" '
             f'to="{to} {cx} {cy}" dur="{abs(dur)}s" repeatCount="indefinite"/>')
        for k, it in enumerate(items):
            a = 2 * math.pi * k / len(items)
            x, y = cx + r * math.cos(a), cy + r * math.sin(a)
            cw = len(it) * 7.4 + 26
            g += (f'<g transform="translate({x:.1f} {y:.1f})"><g>'
                  f'<animateTransform attributeName="transform" type="rotate" from="{-frm}" to="{-to}" dur="{abs(dur)}s" repeatCount="indefinite"/>'
                  f'<rect x="{-cw/2:.1f}" y="-14" width="{cw:.1f}" height="28" fill="{INK}" stroke="{col}"/>'
                  f'<text x="0" y="4.5" text-anchor="middle" class="m" font-size="11.5" fill="{TEXT}">{esc(it)}</text></g></g>')
        body.append(g + "</g>")
    body.append(f'<circle cx="{cx}" cy="{cy}" r="46" fill="{INK}" stroke="{GOLD}"/>'
                f'<circle cx="{cx}" cy="{cy}" r="46" stroke="{GOLD}" stroke-opacity=".4">'
                f'<animate attributeName="r" values="46;58;46" dur="5s" repeatCount="indefinite"/>'
                f'<animate attributeName="stroke-opacity" values=".4;0;.4" dur="5s" repeatCount="indefinite"/></circle>'
                f'<text x="{cx}" y="{cy+7}" text-anchor="middle" class="s" font-size="21" fill="{GOLD}">Claude</text>')
    for i, (lbl, col) in enumerate([("inner · AI core", GOLD_DIM), ("middle · apps & UI", RULE), ("outer · data & infra", RULE)]):
        body.append(f'<rect x="56" y="{h-92+i*24}" width="9" height="9" fill="{INK}" stroke="{col if i else GOLD}"/>'
                    f'<text x="74" y="{h-83.5+i*24}" class="m" font-size="11" letter-spacing="1.5" fill="{MUTED}">{esc(lbl.upper())}</text>')
    write("stack.svg", svg(w, h, "".join(body)))


def concept(today):
    name, idea, arxiv = AGENT_PATTERNS[today.toordinal() % len(AGENT_PATTERNS)]
    w, h = 1000, 190
    body = (card(w, h) + label(56, 62, f"Pattern of the day · {today:%d %b %Y}", GOLD)
            + f'<text x="56" y="114" class="s rise" font-size="36" fill="{TEXT}" style="animation-delay:.2s">{esc(name)}</text>'
            + rule(56, 132, 300, GOLD, .6)
            + f'<text x="56" y="160" class="rise" font-size="14.5" fill="{SOFT}" style="animation-delay:.4s">{esc(idea)}</text>'
            + f'<text x="{w-56}" y="62" text-anchor="end" class="m fade" font-size="11" letter-spacing="2" fill="{MUTED}">ARXIV:{arxiv}</text>')
    write("concept.svg", svg(w, h, body))


def divider():
    w, h = 1000, 28
    body = (f'<defs><linearGradient id="fade" x1="0" x2="1"><stop offset="0" stop-color="{RULE}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{RULE}"/><stop offset="1" stop-color="{RULE}" stop-opacity="0"/></linearGradient></defs>'
            f'<line x1="0" y1="14" x2="{w}" y2="14" stroke="url(#fade)"/>'
            f'<rect x="{w/2-4}" y="10" width="8" height="8" fill="{GOLD}" transform="rotate(45 {w/2} 14)"/>'
            f'<rect y="13.5" width="60" height="1" fill="{GOLD}" opacity=".7"><animate attributeName="x" values="-60;{w};-60" dur="14s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="0;.7;.7;0;0" keyTimes="0;.1;.4;.5;1" dur="14s" repeatCount="indefinite"/></rect>')
    write("divider.svg", svg(w, h, body))


def footer(now):
    w, h = 1000, 170
    body = (rule(300, 30, 700, RULE, 0)
            + diamond(w / 2, 30, 9, GOLD, "breathe")
            + f'<text x="{w/2}" y="88" text-anchor="middle" class="s rise" font-size="30" fill="{TEXT}" style="animation-delay:.2s">Thank you for visiting.</text>'
            + f'<text x="{w/2}" y="122" text-anchor="middle" class="m fade" font-size="10.5" letter-spacing="2.6" fill="{DIM}" style="animation-delay:.5s">'
              f'RE-RENDERED {now:%d %b %Y · %H:%M} UTC · GITHUB.COM/{USER.upper()}</text>')
    write("footer.svg", svg(w, h, body))


def tiles(values, y, w, h0=86):
    """A row of figures: a big didone number over a mono label, hairlines between them."""
    tw = (w - 112) / len(values)
    out = []
    for i, (val, lbl, gold) in enumerate(values):
        x = 56 + i * tw
        if i:
            out.append(f'<line x1="{x:.0f}" y1="{y}" x2="{x:.0f}" y2="{y+h0}" stroke="{LINE}"/>')
        out.append(f'<g class="rise" style="animation-delay:{.15 + i*.1:.2f}s">'
                   f'<text x="{x + (0 if i == 0 else 24):.0f}" y="{y+46}" class="s" font-size="40" fill="{GOLD if gold else TEXT}">{esc(val)}</text>'
                   f'<text x="{x + (0 if i == 0 else 24):.0f}" y="{y+72}" class="m" font-size="10.5" letter-spacing="2.4" fill="{MUTED}">{esc(lbl.upper())}</text></g>')
    return "".join(out)


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
    w, h, x0, y0, s = 1000, 260, 76, 92, 16
    start = days[0][0] - dt.timedelta(days=(days[0][0].weekday() + 1) % 7)
    css = (f".c{{animation:pop .7s {EASE} both;transform-box:fill-box;transform-origin:center}}"
           "@keyframes pop{from{opacity:0;transform:scale(.3)}}")
    body = [card(w, h), label(56, 62, "Contributions · last 12 months", GOLD),
            f'<text x="{w-56}" y="64" text-anchor="end" class="s fade" font-size="22" fill="{TEXT}">{total:,}'
            f'<tspan class="m" font-size="10.5" letter-spacing="2.4" fill="{MUTED}">  CONTRIBUTIONS</tspan></text>']
    seen = set()
    for d, c, lvl in days:
        col, row = (d - start).days // 7, (d.weekday() + 1) % 7
        x, y = x0 + col * s, y0 + row * s
        body.append(f'<rect class="c" x="{x}" y="{y}" width="12" height="12" rx="1.5" fill="{HEAT[min(lvl, 4)]}" '
                    f'style="animation-delay:{col*18}ms"><title>{c} on {d:%d %b %Y}</title></rect>')
        if d.day <= 7 and row == 0 and (d.year, d.month) not in seen:
            seen.add((d.year, d.month))
            body.append(f'<text x="{x}" y="{y0-12}" class="m" font-size="10" letter-spacing="1" fill="{MUTED}">{d:%b}</text>')
    for row, lbl in [(1, "Mon"), (3, "Wed"), (5, "Fri")]:
        body.append(f'<text x="40" y="{y0+row*s+10}" class="m" font-size="9.5" fill="{DIM}">{lbl}</text>')
    lx = w - 56 - 5 * 16 - 64
    body.append(f'<text x="{lx}" y="{h-30}" class="m" font-size="9.5" letter-spacing="1" fill="{DIM}">LESS</text>')
    body += [f'<rect x="{lx+36+i*16}" y="{h-40}" width="12" height="12" rx="1.5" fill="{c}"/>' for i, c in enumerate(HEAT)]
    body.append(f'<text x="{lx+36+5*16+6}" y="{h-30}" class="m" font-size="9.5" letter-spacing="1" fill="{DIM}">MORE</text>')
    write("heatmap.svg", svg(w, h, "".join(body), css))


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
    w, h = 1000, 270
    body = [card(w, h), label(56, 62, "Telemetry", GOLD),
            label(w - 56, 62, f"best day: {best_c} on {best_d:%d %b %Y}", MUTED, "end"),
            tiles([(f"{total:,}", "contributions / yr", True), (f"{cur}d", "current streak", False),
                   (f"{longest}d", "longest streak", False), (f"{active}", "active days", False),
                   (str(len(repos)) if repos is not None else "—", "public repos", False)], 88, w)]
    if repos:
        langs = Counter(r["language"] for r in repos if r.get("language")).most_common(6)
        n = sum(c for _, c in langs) or 1
        shades = [GOLD, TEXT, "#A8A49C", "#6E6B66", "#4A4845", "#33312F"]
        body.append(label(56, 206, "languages · by public repo count", MUTED, size=10))
        x = 56.0
        for i, (lang, c) in enumerate(langs):
            seg = (w - 112) * c / n
            body.append(f'<rect class="draw" x="{x:.1f}" y="216" width="{max(seg-2, 2):.1f}" height="3" fill="{shades[i]}" style="animation-delay:{.3 + i*.12:.2f}s"/>'
                        f'<rect x="{56+i*150}" y="236" width="7" height="7" fill="{shades[i]}" transform="rotate(45 {59.5+i*150} 239.5)"/>'
                        f'<text x="{70+i*150}" y="243" class="m" font-size="11" fill="{SOFT}">{esc(lang)} <tspan fill="{MUTED}">{100*c/n:.0f}%</tspan></text>')
            x += seg
    write("stats.svg", svg(w, h, "".join(body)))


def shiplog(tiles_, releases):
    w, h = 1000, 420
    css = (f".bar{{animation:grow 1.4s {EASE} both;transform-box:fill-box;transform-origin:50% 100%}}"
           "@keyframes grow{from{transform:scaleY(0)}}")
    body = [card(w, h), label(56, 62, "AURA · ship log", GOLD),
            label(w - 56, 62, "from AURA's public README + CHANGELOG, every 6h", MUTED, "end"),
            tiles([(v, l, i == 0) for i, (v, l) in enumerate(tiles_)], 84, w)]
    base, top = 340, 210
    peak = max(r["tests"] or 0 for r in releases) or 1
    slot = (w - 112) / len(releases)
    body.append(label(56, 196, "tests per release, as its changelog states · ~ approximate · — not stated", DIM, size=9.5)
                + f'<line x1="56" y1="{base}" x2="{w-56}" y2="{base}" stroke="{RULE}"/>')
    pts, under = [], len(body)
    for i, r in enumerate(releases):
        cx = 56 + slot * (i + .5)
        latest = i == len(releases) - 1
        if r["tests"]:
            bh = (base - top) * r["tests"] / peak
            pts.append(f"{cx:.1f},{base-bh:.1f}")
            body.append(f'<rect class="bar" x="{cx-9:.1f}" y="{base-bh:.1f}" width="18" height="{bh:.1f}" fill="{GOLD if latest else "#3A3936"}" '
                        f'style="animation-delay:{.2 + i*.06:.2f}s"/>'
                        f'<text x="{cx:.1f}" y="{base-bh-9:.1f}" text-anchor="middle" class="m fade" font-size="10.5" fill="{GOLD if latest else SOFT}" '
                        f'style="animation-delay:{.6 + i*.06:.2f}s">{"~" if r["approx"] else ""}{r["tests"]:,}</text>')
        else:
            body.append(f'<rect x="{cx-9:.1f}" y="{base-5}" width="18" height="5" stroke="{DIM}" stroke-dasharray="2 2"/>'
                        f'<text x="{cx:.1f}" y="{base-13}" text-anchor="middle" class="m" font-size="10.5" fill="{DIM}">—</text>')
        body.append(f'<text x="{cx:.1f}" y="{base+20}" text-anchor="middle" class="m" font-size="11" fill="{GOLD if latest else TEXT}">v{esc(r["v"])}</text>'
                    f'<text x="{cx:.1f}" y="{base+35}" text-anchor="middle" class="m" font-size="9.5" fill="{DIM}">{r["date"]:%d %b}</text>')
    if len(pts) > 1:
        body.insert(under, f'<polyline points="{" ".join(pts)}" stroke="{MUTED}" stroke-opacity=".5" stroke-dasharray="2 4"/>')
    first, last = releases[0], releases[-1]
    days = (last["date"] - first["date"]).days
    caption = f"{len(releases)} releases in {days} days · latest v{last['v']}" + (f" · {last['theme']}" if last["theme"] else "")
    body.append(f'<text x="{w/2}" y="{h-26}" text-anchor="middle" class="m" font-size="10.5" letter-spacing="1.2" fill="{SOFT}">{esc(caption.upper())}</text>')
    write("shiplog.svg", svg(w, h, "".join(body), css))


def aura_receipts():
    """AURA's own published numbers — README badges plus one entry per CHANGELOG release, oldest first.
    Test counts are taken as written: bold "**N tests" is exact, "~N on" is approximate, else None."""
    base = f"https://raw.githubusercontent.com/{USER}/{AURA_REPO}/main"
    readme, log = fetch(f"{base}/README.md"), fetch(f"{base}/CHANGELOG.md")
    badges = dict(re.findall(r"img\.shields\.io/badge/([a-z_]+)-([^?\"]+?)-[0-9a-fA-F]{6}\?", readme))
    tiles = [(badges["version"], "current version"), (badges["gated_sprints"], "gated sprints"),
             (badges["waves_shipped"], "waves shipped"), (re.match(r"\d+", badges["keyless_tests"]).group(), "keyless tests passing")]
    releases = []
    for m in re.finditer(r"^## \[([\d.]+)\] — (\d{4}-\d{2}-\d{2})\n(.*?)(?=^## \[|\Z)", log, re.M | re.S):
        intro = m.group(3).strip().split("\n\n")[0]
        exact, approx = re.search(r"\*\*([\d,]+) tests", intro), re.search(r"~([\d,]+) on", intro)
        hit = exact or approx
        theme = re.search(r"(Waves? [\d–-]+) — (?:\*\*([^*]+)\*\*|([^(]+?) \()", intro)
        releases.append(dict(v=m.group(1), date=dt.date.fromisoformat(m.group(2)),
                             tests=int(hit.group(1).replace(",", "")) if hit else None, approx=exact is None and approx is not None,
                             theme=f"{theme.group(1)} — {theme.group(2) or theme.group(3)}" if theme else None))
    if len(releases) < 2:
        raise ValueError("fewer than two releases parsed from CHANGELOG.md")
    return tiles, releases[::-1]


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
    for f in (hero, about, builds, swarm, stack, divider):
        f()
    concept(today)
    footer(now)
    try:
        shiplog(*aura_receipts())
    except Exception as e:  # noqa: BLE001 — keep the last good ship log rather than drawing a wrong one
        print(f"  AURA receipts fetch failed, keeping existing shiplog: {e}")
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
