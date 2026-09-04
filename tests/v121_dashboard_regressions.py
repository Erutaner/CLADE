"""v12.1 regressions - dashboard redesign.

Static pins (always run): the page keeps every anchor the engine drives and
the mock/stress drives assert (tab markup, canvas id, payload marker, verdict
colour bindings, glossary vocabulary, escaping helpers), plus the v12.1
additions (vital-signs band, attention strip, per-cell records, level of
detail, minimap, measured text budgets).

Visual audit (runs only when a headless Chrome/Edge binary and a rendered
mock repository are both present; otherwise reported as skipped): renders the
real DASHBOARD payload at three viewports and in five interaction states and
asserts zero JavaScript errors, zero overlapping visible texts on the canvas
and zero clipped/overprinting texts in the HTML overlays.
"""
import html as _html
import json
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "engine"))
sys.path.insert(0, str(HERE))
from _check import check, done  # noqa: E402

import edash  # noqa: E402

TPL = edash._TEMPLATE


def static_pins() -> None:
    for view, label in (("overview", "Overview"), ("evaluation", "Evaluation"),
                        ("resources", "Resources"), ("infrastructure", "Infrastructure")):
        check(re.search(rf'<button id="tab-{view}"[^>]*data-view="{view}"[^>]*>{label}</button>', TPL) is not None
              and f'id="view-{view}"' in TPL, f"tab + panel markup for {view}")
    for copy in ("Phylogeny &middot; evolution atlas", "Evaluation matrix",
                 "Cumulative project contract", "Real integrated preflight"):
        check(copy in TPL, f"view copy kept: {copy}")
    check('<svg id="cv">' in TPL and "const DATA = @@DATA@@; /*END-DATA*/" in TPL
          and TPL.count("@@DATA@@") == 1 and TPL.count("@@TITLE@@") == 1,
          "canvas id and single payload/title markers")
    for verdict in ("specialist", "tradeoff", "promising", "dominant", "improved", "regressed"):
        check(f"--{verdict}:" in TPL and re.search(rf'\b{verdict}\s*:\s*"var\(--{verdict}\)"', TPL) is not None,
              f"{verdict} bound through CSS and JS")
    check('["specialist",VC.specialist' in TPL and '["tradeoff",VC.tradeoff' in TPL,
          "legend rows keep the verdict->colour binding")
    # stress-drive markers: the S/P frontier marks are written as HTML entities
    # in the template source (the drive asserts the literal strings)
    for marker in ('SCIENCE_MODE?"S":"I"', "&#9733; inheritance", "P&#9670;",
                   "scientific inheritance frontier", "observed performance frontier"):
        check(marker in TPL, f"stress-drive template marker kept: {marker}")
    check("--faint:#9c9586" in TPL and 'role="img" aria-label="No completed round trend yet"' in TPL
          and 'svg.setAttribute("aria-label"' in TPL, "round trace keeps its screen-reader summary")
    check('esc(DATA.project.primary||"result")' in TPL and 'esc(DATA.project.primary||"")' in TPL,
          "the configured result key is escaped before every innerHTML insertion")
    check("user-focus lanes" in TPL and "FOCUS_BY_ID" in TPL and 'kv("user focus"' in TPL,
          "focus directions and lane allocation stay visible")
    for needle in ("reference evidence", "referenceResult", "predicted [", "numeric observations",
                   "pre-registered stop audit", "training-seed contract", "targeted ablation",
                   "cheap evidence plan", "causal settlement", "fitText"):
        check(needle in TPL, f"auditable evidence surface kept: {needle}")
    # v12.1 additions
    check('id="kpis"' in TPL and 'id="strip"' in TPL and 'id="records"' in TPL and 'id="topAlerts"' in TPL,
          "vital-signs band, attention strip and records strip exist")
    check('id="minimap"' in TPL and "function minimapDraw" in TPL and "function clampView" in TPL,
          "minimap and boot clamp exist")
    check("function fitSegments" in TPL and 'classList.toggle("lod1"' in TPL and 'classList.toggle("lod2"' in TPL,
          "segment-aware truncation and level-of-detail classes exist")
    check("getComputedTextLength" in TPL and "rightEdge" in TPL,
          "card texts are budgeted against their measured neighbours")
    check('id="glossaryBtn"' in TPL and "const GLOSS={" in TPL and "graph_cycle:" in TPL,
          "glossary button and vocabulary present")
    for key in ("improved", "regressed", "inconclusive", "failed", "screened_out", "promising", "dominant",
                "specialist", "tradeoff", "noninferior", "pending", "enabled", "inheritance_frontier",
                "performance_frontier", "record", "noise_floor", "canary", "gate", "stagnation", "level"):
        check(re.search(rf"\n\s*{key}:\"", TPL) is not None, f"glossary explains {key}")
    check('replace(/\'/g,"&#39;")' in TPL, "esc() neutralises apostrophes (title attributes)")
    check("localStorage" in TPL and "scrollPos" in TPL and "saveScrollBeforeReload" in TPL,
          "reading position and view state survive the live reload")
    check("legendCollapsed" in TPL and "handPlaced" in TPL, "legend collapse and hand-placement memory")
    out = edash._fill_template("t", '{"literal":"@@TITLE@@ / @@DATA@@"}')
    check(out.count("const DATA = ") == 1 and '{"literal":"@@TITLE@@ / @@DATA@@"}' in out and "@@TITLE@@ / @@DATA@@" in out,
          "template expansion is single-pass")
    check("<title>t</title>" in out, "title marker expands")


def _chrome() -> str | None:
    for candidate in (r"C:\Program Files\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
                      r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
                      "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser"):
        if os.path.exists(candidate):
            return candidate
    return None


PROBE_HEAD = """<script>window.__errs=[];window.addEventListener('error',e=>window.__errs.push(String(e.message)));
const __ce=console.error;console.error=function(){window.__errs.push('console.error: '+[...arguments].join(' '));__ce.apply(console,arguments)};</script>"""
PROBE_TAIL = """<script>(function(){
function ov(a,b,pad){return !(a.right-pad<=b.left||b.right-pad<=a.left||a.bottom-pad<=b.top||b.bottom-pad<=a.top)}
function vis(e){while(e&&e!==document.body){const st=getComputedStyle(e);if(st.display==='none'||st.visibility==='hidden'||parseFloat(st.opacity)<0.3)return false;e=e.parentElement}return true}
function run(){const rep={errors:window.__errs.slice(),svg:[],clipped:[],html:[]};
const t=[...document.querySelectorAll('#cv text')].filter(x=>x.textContent.trim()&&vis(x)&&x.getBoundingClientRect().width>0);
for(let i=0;i<t.length;i++)for(let j=i+1;j<t.length;j++){const a=t[i].getBoundingClientRect(),b=t[j].getBoundingClientRect();if(ov(a,b,1))rep.svg.push([t[i].textContent.slice(0,30),t[j].textContent.slice(0,30)])}
const all=[...document.querySelectorAll('body *')].filter(e=>!e.closest('svg'));
const scrollable=e=>{while(e&&e!==document.body){const o=getComputedStyle(e);if(/(auto|scroll)/.test(o.overflowX))return true;e=e.parentElement}return false};
all.forEach(el=>{const st=getComputedStyle(el);if(st.display==='none'||st.visibility==='hidden')return;const r=el.getBoundingClientRect();if(r.width<2||r.height<2)return;
 if(st.whiteSpace==='nowrap'&&el.scrollWidth>el.clientWidth+2&&st.overflow!=='hidden'&&st.textOverflow!=='ellipsis'&&el.children.length===0)rep.clipped.push(['nowrap',el.textContent.trim().slice(0,40)]);
 if(el.children.length===0&&el.textContent.trim()&&r.right>innerWidth+1&&st.position!=='fixed'&&!scrollable(el.parentElement))rep.clipped.push(['offscreen',el.textContent.trim().slice(0,40)]);});
const leaves=all.filter(el=>el.children.length===0&&el.textContent.trim()&&vis(el)&&el.getBoundingClientRect().width>0);
const box=e=>e.closest('.card2,#panel,#glossary,#legend,#controls,#tooltip,#strip,#kpis,#status,#minimap');
for(let i=0;i<leaves.length;i++)for(let j=i+1;j<leaves.length;j++){const A=leaves[i],B=leaves[j];if(box(A)!==box(B))continue;
 const a=A.getBoundingClientRect(),b=B.getBoundingClientRect();if(a.top>innerHeight||b.top>innerHeight)continue;if(ov(a,b,2))rep.html.push([A.textContent.trim().slice(0,30),B.textContent.trim().slice(0,30)])}
const pre=document.createElement('pre');pre.id='__report';pre.style.display='none';pre.textContent=JSON.stringify(rep);document.body.appendChild(pre)}
setTimeout(run,900)})();</script>"""

STATES = [
    ("overview", (1600, 1000), "localStorage.clear()"),
    ("overview-laptop", (1280, 800), "localStorage.clear()"),
    ("overview-narrow", (1024, 700), "localStorage.clear()"),
    ("panel", (1600, 1000), "localStorage.clear();document.querySelector('.node').dispatchEvent(new MouseEvent('click',{bubbles:true}))"),
    ("evaluation", (1600, 1000), "localStorage.clear();document.getElementById('tab-evaluation').click()"),
    ("resources", (1600, 1000), "localStorage.clear();document.getElementById('tab-resources').click()"),
    ("infrastructure", (1600, 1000), "localStorage.clear();document.getElementById('tab-infrastructure').click()"),
    ("glossary", (1600, 1000), "localStorage.clear();document.getElementById('glossaryBtn').click()"),
]


def visual_audit() -> None:
    chrome = _chrome()
    repo_html = None
    for candidate in (HERE / "out" / "proj" / ".evo" / "views" / "DASHBOARD.html",
                      HERE / "out" / "proj_stress" / ".evo" / "views" / "DASHBOARD.html"):
        if candidate.exists():
            repo_html = candidate
            break
    if chrome is None or repo_html is None:
        print("  visual audit skipped (needs a headless Chrome/Edge binary and a rendered "
              "tests/out/proj*/.evo/views/DASHBOARD.html from mock_drive or stress_drive)")
        return
    payload = re.search(r"const DATA = (.*); /\*END-DATA\*/", repo_html.read_text(encoding="utf-8")).group(1)
    page = edash._fill_template("visual audit", payload)
    work = HERE / "out" / "v121_visual"
    work.mkdir(parents=True, exist_ok=True)
    for name, size, setup in STATES:
        doc = page.replace("<head>", "<head>" + PROBE_HEAD, 1).replace(
            "</body>", "<script>" + setup + "</script>" + PROBE_TAIL + "</body>", 1)
        path = work / f"{name}.html"
        path.write_text(doc, encoding="utf-8")
        proc = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-sandbox", "--hide-scrollbars",
                               "--allow-file-access-from-files", "--virtual-time-budget=4000",
                               f"--window-size={size[0]},{size[1]}", "--dump-dom", path.resolve().as_uri()],
                              capture_output=True, text=True, timeout=120, encoding="utf-8", errors="replace")
        m = re.search(r'<pre id="__report"[^>]*>(.*?)</pre>', proc.stdout, re.S)
        check(m is not None, f"{name}: the probe ran inside headless Chrome")
        if m is None:
            continue
        rep = json.loads(_html.unescape(m.group(1)))
        check(not rep["errors"], f"{name}: no JavaScript errors: {rep['errors'][:3]}")
        check(not rep["svg"], f"{name}: no overlapping texts on the canvas: {rep['svg'][:3]}")
        check(not rep["clipped"], f"{name}: no clipped or off-screen texts: {rep['clipped'][:3]}")
        check(not rep["html"], f"{name}: no overprinting texts in the overlays: {rep['html'][:3]}")


def main() -> None:
    static_pins()
    visual_audit()
    done("V12.1 DASHBOARD REGRESSIONS")


if __name__ == "__main__":
    main()
