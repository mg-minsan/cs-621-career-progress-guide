"""
Original flat 'doodle' icons and decorations for the Streamlit app (Step 6).
Drawn from scratch as SVG, in the style of flat career-planner slide decks:
navy outlines, sunny colours, offset colour blobs, sparkles, a winding road.
No external images, so the app works offline.
"""
from __future__ import annotations

import base64

# Layout palette from the teal career-planner deck (cream paper, teal hills, ink lines);
# icon fills stay bright like the pink-purple deck's colourful icons.
NAVY, YELLOW, ORANGE, TEAL, BLUE, PINK, RED, GREEN, LILAC, CREAM, PURPLE = (
    "#1f2a30", "#ffc93c", "#ff8a3d", "#2bb3a0", "#4c7cf0", "#ff5fa2", "#ff4d5e", "#4cc46a", "#efe6ff", "#f5f1e8",
    "#b45cf0")
TEAL_UI, TEAL_DARK, TEAL_SOFT = "#6aa8b6", "#3d7c8a", "#dcecef"
S = f'stroke="{NAVY}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"'


def _svg(body: str, w: int = 64, h: int = 64) -> str:
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}">{body}</svg>'


def sparkle(x, y, r, color=ORANGE) -> str:
    """4-point star, the sparkle used all over the decks."""
    q = r * 0.28
    return (f'<path d="M{x} {y-r} Q{x+q} {y-q} {x+r} {y} Q{x+q} {y+q} {x} {y+r} '
            f'Q{x-q} {y+q} {x-r} {y} Q{x-q} {y-q} {x} {y-r}Z" fill="{color}"/>')


def _hills_bg() -> str:
    """Overlapping teal circles along the bottom edge, like the deck's scalloped hills."""
    circles = "".join(f'<circle cx="{x}" cy="{y}" r="{r}" fill="#6aa8b6"/>' for x, y, r in
                      [(60, 250, 120), (260, 270, 110), (450, 240, 130), (660, 275, 105), (860, 250, 125),
                       (1060, 270, 110), (1250, 245, 130), (1450, 275, 110), (1640, 250, 125)])
    svg = f'<svg xmlns="http://www.w3.org/2000/svg" width="1700" height="260" opacity=".9">{circles}</svg>'
    return "data:image/svg+xml;base64," + base64.b64encode(svg.encode()).decode()


def blob(color, cx=34, cy=36, r=26) -> str:
    """Soft glowing disc behind each icon (the deck's blurred colour blobs)."""
    gid = "g" + color.strip("#")
    return (f'<defs><radialGradient id="{gid}"><stop offset="0" stop-color="{color}" stop-opacity=".55"/>'
            f'<stop offset="1" stop-color="{color}" stop-opacity="0"/></radialGradient></defs>'
            f'<circle cx="{cx}" cy="{cy}" r="{r + 4}" fill="url(#{gid})"/>')


ICONS = {
    # ---- the five stages of the agent
    "profile": blob(YELLOW) + f'''
      <rect x="10" y="16" width="44" height="32" rx="5" fill="#fff" {S}/>
      <circle cx="23" cy="29" r="5" fill="{ORANGE}" {S}/>
      <path d="M15 42c1-5 4-7 8-7s7 2 8 7" fill="{ORANGE}" {S}/>
      <path d="M36 26h12M36 32h12M36 38h8" {S}/>''' + sparkle(54, 12, 5, PINK),
    "confirm_role": blob(TEAL) + f'''
      <path d="M24 20v-4a3 3 0 0 1 3-3h10a3 3 0 0 1 3 3v4" fill="none" {S}/>
      <rect x="9" y="20" width="44" height="30" rx="5" fill="{ORANGE}" {S}/>
      <path d="M9 32h44" {S}/><rect x="28" y="29" width="7" height="6" rx="1.5" fill="{YELLOW}" {S}/>
      <circle cx="50" cy="47" r="9" fill="{GREEN}" {S}/><path d="M46 47l3 3 5-6" fill="none" stroke="#fff" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round"/>''',
    "choose_path": blob(PINK) + f'''
      <path d="M32 10v46" {S}/><path d="M24 56h16" {S}/>
      <path d="M32 16h20l6 6-6 6H32z" fill="{BLUE}" {S}/>
      <path d="M32 31H12l-6 6 6 6h20z" fill="{YELLOW}" {S}/>''' + sparkle(12, 14, 5, ORANGE),
    "approve_plan": blob(BLUE) + f'''
      <rect x="14" y="12" width="36" height="44" rx="5" fill="#fff" {S}/>
      <rect x="23" y="8" width="18" height="9" rx="3" fill="{YELLOW}" {S}/>
      <path d="M20 27l3 3 5-5M20 38l3 3 5-5" fill="none" stroke="{GREEN}" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/>
      <path d="M32 28h12M32 39h12M20 49h24" {S}/>''',
    "done": blob(YELLOW) + f'''
      <path d="M20 12h24v12a12 12 0 0 1-24 0z" fill="{YELLOW}" {S}/>
      <path d="M20 16h-7a6 6 0 0 0 7 10M44 16h7a6 6 0 0 1-7 10" fill="none" {S}/>
      <path d="M32 36v8" {S}/><rect x="22" y="44" width="20" height="8" rx="2" fill="{ORANGE}" {S}/>
      <path d="M28 18l2 4 4 .5-3 3 1 4-4-2-4 2 1-4-3-3 4-.5z" fill="#fff" stroke="{NAVY}" stroke-width="1.5" stroke-linejoin="round"/>'''
      + sparkle(9, 40, 5, PINK) + sparkle(56, 40, 4, TEAL),
    # ---- plan phases
    "start": blob(GREEN) + f'''
      <path d="M32 44V26" {S}/>
      <path d="M32 30c-2-8-10-11-17-9 1 8 8 12 17 9z" fill="{GREEN}" {S}/>
      <path d="M32 26c2-9 10-12 18-10-1 9-9 13-18 10z" fill="{GREEN}" {S}/>
      <path d="M20 44h24l-3 12H23z" fill="{ORANGE}" {S}/>''',
    "build": blob(BLUE) + f'''
      <rect x="10" y="40" width="20" height="12" rx="2" fill="{BLUE}" {S}/>
      <rect x="34" y="40" width="20" height="12" rx="2" fill="{YELLOW}" {S}/>
      <rect x="22" y="26" width="20" height="12" rx="2" fill="{ORANGE}" {S}/>
      <rect x="27" y="12" width="12" height="12" rx="2" fill="{PINK}" {S}/>''',
    "stand_out": blob(PINK) + f'''
      <path d="M32 8c8 6 12 15 10 28H22C20 23 24 14 32 8z" fill="#fff" {S}/>
      <circle cx="32" cy="24" r="5" fill="{BLUE}" {S}/>
      <path d="M22 30l-7 8 7 1M42 30l7 8-7 1" fill="{RED}" {S}/>
      <path d="M26 40c0 6 3 10 6 14 3-4 6-8 6-14z" fill="{ORANGE}" {S}/>'''
      + sparkle(52, 14, 5, YELLOW) + sparkle(12, 18, 4, TEAL),
    # ---- metric tiles
    "skills": blob(YELLOW) + f'''
      <path d="M32 10a14 14 0 0 0-8 25c2 2 3 4 3 7h10c0-3 1-5 3-7a14 14 0 0 0-8-25z" fill="{YELLOW}" {S}/>
      <path d="M27 48h10M28 53h8" {S}/><path d="M29 30l3 4 3-4" fill="none" {S}/>
      <path d="M8 22l5 2M56 22l-5 2M32 3v3" {S}/>''',
    "subsidy": blob(TEAL) + f'''
      <path d="M10 14h20l24 24-18 18-24-24V14z" fill="{TEAL}" {S}/>
      <circle cx="20" cy="24" r="4" fill="#fff" {S}/>
      <path d="M29 40l12-12" stroke="#fff" stroke-width="3" stroke-linecap="round"/>''',
    "credit": blob(ORANGE) + f'''
      <ellipse cx="32" cy="44" rx="18" ry="7" fill="{YELLOW}" {S}/>
      <path d="M14 36v8M50 36v8" {S}/>
      <ellipse cx="32" cy="36" rx="18" ry="7" fill="{YELLOW}" {S}/>
      <path d="M14 28v8M50 28v8" {S}/>
      <ellipse cx="32" cy="28" rx="18" ry="7" fill="{YELLOW}" {S}/>
      <text x="32" y="32" font-family="Arial" font-weight="700" font-size="10" fill="{NAVY}" text-anchor="middle">$</text>''',
    "pay": blob(PINK) + f'''
      <rect x="8" y="18" width="46" height="34" rx="6" fill="{BLUE}" {S}/>
      <path d="M12 18l26-9 4 9" fill="{YELLOW}" {S}/>
      <rect x="38" y="29" width="18" height="12" rx="4" fill="#fff" {S}/>
      <circle cx="45" cy="35" r="2.5" fill="{NAVY}"/>''',
    # ---- path kinds
    "goal": blob(RED) + f'''
      <circle cx="30" cy="34" r="20" fill="#fff" {S}/><circle cx="30" cy="34" r="13" fill="{RED}" {S}/>
      <circle cx="30" cy="34" r="6" fill="#fff" {S}/>
      <path d="M30 34L54 10" {S}/><path d="M48 8l6 2 2 6-5-1z" fill="{YELLOW}" {S}/>''',
    "nearby": blob(TEAL) + f'''
      <circle cx="32" cy="34" r="22" fill="#fff" {S}/>
      <path d="M32 16l6 18-6 18-6-18z" fill="{ORANGE}" {S}/><path d="M26 34h12" {S}/>
      <circle cx="32" cy="34" r="3" fill="{NAVY}"/>''',
    "warning": f'''<path d="M32 8l26 46H6z" fill="{YELLOW}" {S}/><path d="M32 24v14" {S}/><circle cx="32" cy="45" r="2.5" fill="{NAVY}"/>''',
}

HILLS_BG = _hills_bg()

STAGE_COLORS = {"profile": YELLOW, "confirm_role": TEAL, "choose_path": PINK, "approve_plan": BLUE, "done": ORANGE}


def icon_uri(name: str, w: int = 64, h: int = 64) -> str:
    return "data:image/svg+xml;base64," + base64.b64encode(_svg(ICONS[name], 64, 64).encode()).decode()


def icon(name: str, size: int = 44) -> str:
    return f'<img src="{icon_uri(name)}" width="{size}" height="{size}" alt="" style="vertical-align:middle">'


# ---------------------------------------------------------------- hero: winding road with checkpoints
def _bez(p0, p1, p2, p3, t):
    u = 1 - t
    return tuple(u**3 * a + 3 * u * u * t * b + 3 * u * t * t * c + t**3 * d for a, b, c, d in zip(p0, p1, p2, p3))


def hero_svg() -> str:
    seg1 = ((30, 230), (150, 230), (90, 140), (200, 140))
    seg2 = ((200, 140), (310, 140), (260, 50), (390, 50))
    road = "M30 230 C150 230 90 140 200 140 C310 140 260 50 390 50"
    dots = [(_bez(*seg1, 0.06), YELLOW), (_bez(*seg1, 0.62), TEAL), (_bez(*seg2, 0.12), PINK),
            (_bez(*seg2, 0.62), BLUE)]
    pts = "".join(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="11" fill="{c}" {S}/>' for (x, y), c in dots)
    body = f'''
      <defs><linearGradient id="road" x1="0" x2="1"><stop offset="0" stop-color="#6aa8b6"/><stop offset="1" stop-color="#3d7c8a"/></linearGradient>
      <radialGradient id="glow1"><stop offset="0" stop-color="#6aa8b6" stop-opacity=".45"/><stop offset="1" stop-color="#6aa8b6" stop-opacity="0"/></radialGradient>
      <radialGradient id="glow2"><stop offset="0" stop-color="{YELLOW}" stop-opacity=".6"/><stop offset="1" stop-color="{YELLOW}" stop-opacity="0"/></radialGradient></defs>
      <circle cx="330" cy="175" r="95" fill="url(#glow1)"/><circle cx="90" cy="70" r="70" fill="url(#glow2)"/>
      <path d="{road}" fill="none" stroke="{NAVY}" stroke-width="30" stroke-linecap="round"/>
      <path d="{road}" fill="none" stroke="url(#road)" stroke-width="24" stroke-linecap="round"/>
      <path d="{road}" fill="none" stroke="#fff" stroke-width="2.5" stroke-dasharray="10 10"/>
      {pts}
      <path d="M390 50c0-14 10-24 22-24s22 10 22 24c0 16-22 34-22 34s-22-18-22-34z" transform="translate(-22 -48)"
            fill="{ORANGE}" {S}/>
      <circle cx="390" cy="26" r="7" fill="#fff" {S}/>
      <path d="M70 196v-36" {S}/><path d="M70 160h26l-6 7 6 7H70z" fill="{RED}" {S}/>
      {sparkle(250, 210, 10, YELLOW)}{sparkle(330, 120, 7, PINK)}{sparkle(40, 120, 8, TEAL)}
      {sparkle(150, 40, 9, ORANGE)}{sparkle(430, 110, 6, BLUE)}'''
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 450 260" width="100%" style="max-width:450px">{body}</svg>'


def hero_img() -> str:
    uri = "data:image/svg+xml;base64," + base64.b64encode(hero_svg().encode()).decode()
    return f'<img src="{uri}" alt="A winding road with checkpoints" style="width:100%;max-width:450px">'


# ---------------------------------------------------------------- the stage roadmap (progress bar)
def roadmap_html(steps: list[tuple[str, str]], now: int) -> str:
    items = []
    for i, (key, label) in enumerate(steps):
        state = "now" if i == now else ("done" if i < now else "todo")
        tick = '<span class="rm-tick">✓</span>' if state == "done" else ""
        items.append(f'<div class="rm-step {state}"><div class="rm-badge" style="--c:{STAGE_COLORS[key]}">'
                     f'{icon(key, 40)}{tick}</div><div class="rm-label">{label}</div></div>')
    return f'<div class="roadmap">{"".join(items)}</div>'


CSS = f"""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Serif+Display&family=Nunito+Sans:wght@400;600;700;800&display=swap');
html, body, .stMarkdown, p, label, input, textarea, button, li {{font-family: 'Nunito Sans', sans-serif;}}
h1, h2, h3, h4, .big-title, .serif {{font-family: 'DM Serif Display', Georgia, serif !important; color: {TEAL_DARK};
  font-weight: 400 !important; letter-spacing: -.01em;}}
.stApp {{background-color: {CREAM};
  background-image: url("{HILLS_BG}"); background-repeat: repeat-x; background-position: bottom left;
  background-size: auto 105px; background-attachment: fixed;}}
.block-container {{max-width: 1120px; padding-top: 2.6rem; padding-bottom: 170px;}}
header[data-testid="stHeader"] {{background: transparent;}}
section[data-testid="stSidebar"] {{background: #ece6da; border-right: 1.5px solid {NAVY};}}

/* top bar like the deck's outlined header pill */
.topbar {{display:flex; justify-content:space-between; align-items:center; border:1.5px solid {NAVY};
  border-radius:999px; padding: 5px 16px; font-size:.72rem; font-weight:800; letter-spacing:.08em;
  text-transform:uppercase; color:{NAVY}; margin-bottom: 1.1rem; background: rgba(255,255,255,.4);}}

/* roadmap progress bar: a teal road with checkpoints */
.roadmap {{display:flex; justify-content:space-between; position:relative; margin: 0 0 1.5rem; padding: 0 6px;}}
.roadmap:before {{content:""; position:absolute; left:46px; right:46px; top:30px; height:14px; border-radius:8px;
  background: {TEAL_UI}; border: 1.5px solid {NAVY};}}
.roadmap:after {{content:""; position:absolute; left:52px; right:52px; top:37px; height:0;
  border-top: 2px dashed #fff;}}
.rm-step {{position:relative; z-index:1; text-align:center; width:120px;}}
.rm-badge {{width:70px; height:70px; margin:0 auto; border-radius:50%; background:#fff; border:1.5px solid {NAVY};
  display:flex; align-items:center; justify-content:center; position:relative; transition: transform .2s;}}
.rm-step.now .rm-badge {{background: {TEAL_SOFT}; border: 3px solid {TEAL_DARK}; transform: scale(1.15);
  box-shadow: 0 0 0 6px rgba(106,168,182,.25);}}
.rm-step.todo .rm-badge {{background: {CREAM}; border-color: #8b8d8c;}}
.rm-step.todo .rm-badge img {{filter: grayscale(.8); opacity:.6;}}
.rm-tick {{position:absolute; right:-4px; bottom:-2px; background:{TEAL_DARK}; color:#fff; border:2px solid {CREAM};
  width:23px; height:23px; border-radius:50%; font-size:13px; font-weight:800; line-height:19px;}}
.rm-label {{margin-top:9px; font-weight:800; font-size:.84rem; color:{NAVY};}}
.rm-step.now .rm-label {{color:{TEAL_DARK};}}
.rm-step.todo .rm-label {{opacity:.5;}}

/* hero */
.big-title {{font-size: 3.2rem; line-height: 1.0; margin: .2rem 0 .7rem;}}
.big-title span {{font-style: italic; color: {NAVY};}}
.lead {{font-size: 1.05rem; color: #3a464d; margin-bottom: .9rem;}}
.pill {{display:inline-block; padding: 5px 13px; margin: 4px 6px 4px 0; border-radius: 999px; font-weight: 800;
  font-size: .8rem; color: {NAVY}; background: {TEAL_SOFT}; border: 1.5px solid {NAVY};}}
.pill.y {{background:#ffe7a3;}} .pill.t {{background:{TEAL_SOFT};}} .pill.p {{background:#ffd2e4;}} .pill.b {{background:#dce5ff;}}
.check {{display:flex; align-items:center; gap:8px; font-weight:800; font-size:.86rem; color:{NAVY}; margin:4px 0;
  text-transform: uppercase; letter-spacing:.03em;}}
.check:before {{content:"✓"; display:inline-flex; align-items:center; justify-content:center; width:20px; height:20px;
  border-radius:50%; background:{TEAL_DARK}; color:#fff; font-size:.75rem;}}

/* cards */
div[class*="st-key-card"], div[class*="st-key-formcard"] {{background: #fffdf8; border-radius: 22px;
  padding: 16px 20px 12px; border: 1.5px solid {NAVY}; margin-bottom: 12px;
  box-shadow: 6px 6px 0 var(--accent, {TEAL_UI});}}
div[class*="st-key-card0"] {{--accent: {YELLOW};}} div[class*="st-key-card1"] {{--accent: {TEAL_UI};}}
div[class*="st-key-card2"] {{--accent: {PINK};}} div[class*="st-key-card3"] {{--accent: {BLUE};}}
div[class*="st-key-card4"] {{--accent: {ORANGE};}}
div[class*="st-key-formcard"] {{--accent: {TEAL_UI}; padding-top: 10px;}}
div[data-testid="stForm"] {{border: none; padding: 0;}}

/* metric tiles */
.tiles {{display:grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: .5rem 0 1rem;}}
.tile {{border-radius:20px; padding: 13px 15px; border: 1.5px solid {NAVY}; background:#fffdf8 !important;}}
.tile .t-top {{display:flex; align-items:center; gap:8px; font-weight:800; font-size:.82rem; color:{NAVY};
  text-transform: uppercase; letter-spacing:.03em;}}
.tile .t-num {{font-family:'DM Serif Display',serif; font-size:1.9rem; color:{TEAL_DARK}; margin-top:2px;}}
.tile .t-sub {{font-size:.8rem; color:#3a464d;}}
.tile.hl {{background: {TEAL_DARK} !important;}}
.tile.hl .t-top, .tile.hl .t-num, .tile.hl .t-sub {{color:#fff;}}
@media (max-width: 760px) {{ .tiles {{grid-template-columns: repeat(2, 1fr);}} .rm-label {{font-size:.66rem;}}
  .rm-step {{width:62px;}} .rm-badge {{width:52px; height:52px;}} .big-title {{font-size:2.3rem;}} }}

/* phase headers */
.phase {{display:flex; align-items:center; gap:10px; margin: 1.3rem 0 .45rem; flex-wrap: wrap;}}
.phase .ph-name {{font-family:'DM Serif Display',serif; font-size:1.55rem; color:{TEAL_DARK};}}
.phase .ph-pill {{padding:4px 12px; border-radius:999px; font-weight:800; font-size:.76rem; color:{NAVY};
  border:1.5px solid {NAVY};}}

/* buttons, radios, expanders */
.stButton > button, .stDownloadButton > button, div[data-testid="stFormSubmitButton"] > button {{
  border-radius: 999px !important; font-weight: 800 !important; padding: .45rem 1.3rem !important;
  border: 1.5px solid {NAVY} !important; background: #fffdf8; color: {NAVY};}}
.stButton > button[kind="primary"], div[data-testid="stFormSubmitButton"] > button[kind="primaryFormSubmit"],
.stButton > button[data-testid="stBaseButton-primary"],
div[data-testid="stFormSubmitButton"] > button[data-testid="stBaseButton-primaryFormSubmit"] {{
  background: {TEAL_DARK} !important; color: #fff !important; border-color: {NAVY} !important;}}
.stButton > button:hover, div[data-testid="stFormSubmitButton"] > button:hover {{transform: translateY(-1px);
  box-shadow: 3px 3px 0 {NAVY};}}
div[role="radiogroup"] > div {{width: 100%;}}
label[data-testid="stRadioOption"] {{background: #fffdf8; border-radius:16px; padding: 11px 14px;
  margin-bottom: 8px; width: 100%; border: 1.5px solid rgba(31,42,48,.30);}}
label[data-testid="stRadioOption"][data-selected="true"], div[role="radiogroup"] label:has(input:checked) {{
  border: 2px solid {TEAL_DARK}; background: {TEAL_SOFT}; box-shadow: 4px 4px 0 {TEAL_UI};}}
div[data-testid="stExpander"] details {{border: 1.5px solid rgba(31,42,48,.35); border-radius:16px; background: #fffdf8;}}
div[data-testid="stAlert"] {{border-radius: 16px;}}

/* done banner */
.banner {{display:flex; align-items:center; gap:18px; border-radius:24px; padding: 18px 24px; margin-bottom: 1rem;
  background: {TEAL_DARK}; border: 1.5px solid {NAVY}; box-shadow: 6px 6px 0 {YELLOW};}}
.banner .b-title {{font-family:'DM Serif Display',serif; font-size:2rem; color:#fff;}}
.banner .lead {{color: #e8f3f5 !important;}}
</style>
"""

TILE_BG = {}


def tiles_html(rows: list[tuple[str, str, str, str]], highlight: str = "pay") -> str:
    """rows: (icon, label, number, sub). The highlight tile gets the pink-purple gradient."""
    return '<div class="tiles">' + "".join(
        f'<div class="tile{" hl" if i == highlight else ""}" style="background:{TILE_BG.get(i, "#fff")}">'
        f'<div class="t-top">{icon(i, 30)}{lab}</div>'
        f'<div class="t-num">{num}</div><div class="t-sub">{sub}</div></div>' for i, lab, num, sub in rows) + "</div>"


PHASE_STYLE = {"start": ("Start", "#dff3d9", "foundations first"),
               "build": ("Build", "#dce5ff", "the core of the new job"),
               "stand_out": ("Stand out", "#ffd2e4", "what makes you competitive")}


def phase_html(key: str, n: int) -> str:
    name, bg, sub = PHASE_STYLE.get(key, (key, "#fff", ""))
    return (f'<div class="phase">{icon(key, 46)}<span class="ph-name">{name}</span>'
            f'<span class="ph-pill" style="background:{bg}">{n} skill{"s" if n != 1 else ""} · {sub}</span></div>')


def banner_html(title: str, sub: str) -> str:
    return (f'<div class="banner">{icon("done", 72)}<div><div class="b-title">{title}</div>'
            f'<div class="lead" style="margin:0">{sub}</div></div></div>')
