"""
Generates a single self-contained HTML page (searchable/sortable table) from
one of the topics_*.csv files produced by scraping.py.
"""

import base64
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

FIGURE_PATHS = """    <path d="m 86.638917,62.952547 c -0.207674,-0.05858 -0.417801,-0.116207 -0.633325,-0.126664 -0.12653,-0.0061 -0.253315,0 -0.379994,0 h -0.506662 -1.393314 -0.633325 c -0.468519,0 -0.950246,-0.02565 -1.393317,0.126664 -0.215189,0.07397 -0.414077,0.192432 -0.633325,0.253331 -0.207615,0.05767 -0.42777,0.06204 -0.633325,0.126664 -0.180546,0.05676 -0.34324,0.157872 -0.506662,0.25333 -0.244803,0.142995 -0.496377,0.275665 -0.759989,0.379995 -0.211544,0.08372 -0.430999,0.149291 -0.633325,0.253331 -0.270982,0.139344 -0.502798,0.343263 -0.759992,0.506661 -0.207877,0.132067 -0.432346,0.23765 -0.633325,0.379994 -0.172379,0.122088 -0.326139,0.270306 -0.506661,0.379995 -0.24236,0.147264 -0.525503,0.220494 -0.759989,0.379997 -0.198136,0.134777 -0.351387,0.324142 -0.506662,0.506659 -0.232548,0.273346 -0.47752,0.538615 -0.759989,0.759991 -0.332774,0.260801 -0.715914,0.459484 -1.013322,0.75999 -0.29735,0.300447 -0.492428,0.686066 -0.759989,1.013322 -0.264728,0.323791 -0.596304,0.585629 -0.886656,0.886656 -0.31166,0.323119 -0.574824,0.690367 -0.886656,1.01332 -0.248959,0.257838 -0.528174,0.486639 -0.759992,0.759991 -0.258227,0.304493 -0.452013,0.657619 -0.633325,1.01332 -0.385932,0.757129 -0.724104,1.538868 -1.139984,2.27997 -0.231464,0.412471 -0.488752,0.816313 -0.633327,1.266653 -0.131724,0.410309 -0.165114,0.844842 -0.253328,1.266651 -0.180621,0.863669 -0.589602,1.667555 -0.759992,2.5333 -0.16353,0.830887 -0.126664,1.686478 -0.126664,2.533304 v 2.27997 1.26665 c 0,0.380169 -0.037,0.761623 0,1.139987 0.03396,0.347188 0.149792,0.680194 0.253328,1.013319 0.246236,0.792257 0.426665,1.603148 0.633328,2.406637 0.109854,0.427102 0.227366,0.852904 0.379994,1.266653 0.294441,0.79818 0.716015,1.542383 1.139987,2.27997 0.198603,0.345511 0.398643,0.691225 0.633325,1.01332 0.407667,0.559513 0.921392,1.045555 1.519981,1.393317 0.294525,0.17111 0.609236,0.309021 0.886656,0.506661 0.220252,0.156913 0.413533,0.349102 0.633325,0.506659 0.307757,0.220614 0.660701,0.368657 1.01332,0.506661 0.83324,0.326103 1.683479,0.606594 2.5333,0.886656 0.41878,0.138011 0.838128,0.276119 1.266653,0.379994 0.871109,0.211158 1.769397,0.278479 2.659965,0.379997 0.885339,0.100922 1.769054,0.23643 2.659967,0.253328 0.337719,0.0064 0.675543,0 1.013323,0 h 1.26665 c 0.930634,0 1.865035,0.0027 2.786631,-0.126664 0.823194,-0.115569 1.629735,-0.337641 2.406637,-0.633325 0.725541,-0.276136 1.425645,-0.616158 2.153306,-0.886656 0.338194,-0.125719 0.682314,-0.236413 1.01332,-0.379994 0.346526,-0.150313 0.676494,-0.335719 1.013322,-0.506661 0.556501,-0.282427 1.136081,-0.527793 1.646645,-0.886656 0.409959,-0.28815 0.767031,-0.643702 1.145473,-0.97215 0.378443,-0.328448 0.788237,-0.635522 1.261164,-0.801162 0.215435,-0.07545 0.446075,-0.12278 0.633325,-0.25333 0.196323,-0.136876 0.324495,-0.351439 0.506661,-0.506659 0.115993,-0.09884 0.251413,-0.171544 0.379993,-0.25333 0.61442,-0.390802 1.07312,-0.992651 1.39332,-1.646648 0.12462,-0.254528 0.23061,-0.519161 0.37999,-0.759989 0.16064,-0.258974 0.36983,-0.487684 0.50666,-0.759992 0.2352,-0.468089 0.23471,-1.016676 0.38,-1.519981 0.0741,-0.25664 0.1862,-0.501443 0.25333,-0.759989 0.0751,-0.289256 0.0925,-0.58977 0.12666,-0.886656 0.0342,-0.296607 0.0854,-0.59096 0.12667,-0.886656 0.0413,-0.295713 0.0727,-0.592978 0.12666,-0.886655 0.0464,-0.252785 0.10954,-0.503553 0.12667,-0.75999 0.0169,-0.252821 0,-0.506607 0,-0.759991 V 82.458972 81.69898 c 0,-0.126796 0.003,-0.253566 0.008,-0.380262 0.005,-0.126696 0.0104,-0.254297 -0.008,-0.379727 -0.0392,-0.26467 -0.18503,-0.501305 -0.25333,-0.759992 -0.0656,-0.248558 -0.0583,-0.512182 -0.12667,-0.759989 -0.0605,-0.219347 -0.17829,-0.418506 -0.25333,-0.633328 -0.10152,-0.290626 -0.12404,-0.607272 -0.25332,-0.886656 -0.10349,-0.223634 -0.27062,-0.412515 -0.38,-0.633325 -0.11868,-0.239575 -0.16513,-0.507598 -0.25333,-0.759989 -0.14379,-0.411459 -0.39574,-0.774575 -0.63333,-1.139987 -0.26846,-0.412891 -0.52201,-0.835474 -0.75999,-1.26665 -0.34897,-0.757624 -0.774011,-1.480188 -1.266647,-2.153306 -0.409019,-0.558867 -0.864028,-1.083157 -1.266653,-1.646648 -0.122788,-0.171847 -0.240962,-0.347667 -0.379995,-0.506658 -0.295797,-0.338259 -0.676116,-0.589656 -1.013319,-0.886656 -0.426825,-0.375936 -0.783161,-0.823725 -1.139987,-1.26665 -0.112891,-0.140131 -0.22876,-0.282482 -0.379994,-0.379998 -0.158893,-0.102455 -0.348469,-0.149797 -0.506662,-0.25333 -0.150475,-0.09848 -0.264412,-0.242219 -0.379994,-0.379995 -0.153825,-0.183363 -0.316367,-0.361495 -0.506661,-0.506658 -0.317038,-0.241848 -0.701372,-0.38495 -1.01332,-0.633328 -0.176367,-0.140426 -0.325527,-0.311317 -0.482958,-0.472687 -0.157431,-0.161371 -0.327215,-0.31621 -0.530362,-0.413966 -0.205224,-0.09876 -0.438088,-0.136067 -0.633328,-0.253331 -0.130728,-0.07852 -0.240873,-0.19088 -0.379994,-0.25333 -0.121977,-0.05476 -0.25983,-0.06804 -0.379995,-0.126667 -0.109321,-0.05333 -0.199997,-0.144008 -0.253331,-0.253328 z" />
    <path d="m 84.612278,100.57208 c -0.249018,1.13253 -0.460283,2.27336 -0.633325,3.41996 -0.06337,0.41992 -0.121732,0.842 -0.126667,1.26665 -0.0049,0.42247 0.04306,0.84635 0,1.26665 -0.03044,0.2971 -0.106092,0.5887 -0.126664,0.88665 -0.02036,0.29492 0,0.59104 0,0.88666 v 0.88665 1.51998 c 0,0.25335 -0.01096,0.50687 0,0.75999 0.01654,0.3821 0.09941,0.75851 0.126664,1.13999 0.02107,0.29494 0.0088,0.5911 0,0.88666 -0.01129,0.37991 -0.01676,0.76027 0,1.13998 0.01687,0.38228 0.05633,0.76386 0.126667,1.13999 0.158545,0.84787 0.473998,1.67135 0.506658,2.5333 0.01279,0.33761 -0.01826,0.67597 0,1.01332 0.01841,0.34001 0.08668,0.67517 0.126667,1.01332 0.04491,0.37985 0.05425,0.76442 0.126664,1.13999 0.07376,0.38253 0.212398,0.75256 0.25333,1.13998 0.02664,0.25219 0.01129,0.50665 0,0.75999 -0.01128,0.25323 -0.01845,0.50718 0,0.75999 0.02174,0.29788 0.07886,0.59184 0.126664,0.88666 0.04779,0.29471 0.08634,0.59083 0.126667,0.88665 0.0863,0.63309 0.180748,1.26517 0.253331,1.89998 0.03393,0.29676 0.06319,0.59479 0.126664,0.88666 0.04579,0.21058 0.10947,0.4185 0.126664,0.63332 0.01685,0.21054 -0.01144,0.42243 0,0.63333 0.02112,0.38936 0.175858,0.75782 0.25333,1.13998 0.04281,0.21116 0.06225,0.42774 0.126667,0.63333 0.113098,0.36095 0.357283,0.66581 0.506658,1.01332 0.137824,0.32064 0.19184,0.66977 0.253331,1.01332 0.08502,0.47498 0.187722,0.95076 0.379995,1.39332 0.09076,0.2089 0.20179,0.41146 0.25333,0.63332 0.06772,0.29149 0.0295,0.60362 0.126667,0.88666 0.06138,0.17879 0.173406,0.33536 0.25333,0.50666 0.130189,0.27903 0.17218,0.58962 0.253328,0.88665 0.105602,0.38653 0.278428,0.75238 0.379998,1.13999 0.06517,0.24869 0.100426,0.50425 0.126664,0.75999 0.04838,0.47155 0.069,0.95659 0.25333,1.39331 0.0887,0.21014 0.215041,0.40848 0.253331,0.63333 0.04262,0.25026 -0.02862,0.50774 0,0.75999 0.01825,0.16085 0.0767,0.3147 0.148202,0.45994 0.07151,0.14524 0.156341,0.28349 0.231792,0.42672 0.187514,0.35596 0.316429,0.7427 0.379995,1.13998 0.194786,0.39765 0.323728,0.82745 0.379997,1.26665 0.03271,0.25532 0.04177,0.51699 0.126664,0.75999 0.06236,0.17848 0.163463,0.34032 0.253331,0.50666 0.318488,0.5895 0.499003,1.24355 0.633325,1.89998 0.03493,0.17072 0.06715,0.34288 0.126664,0.50666 0.07776,0.214 0.201398,0.41164 0.25333,0.63333 0.02465,0.10523 0.03252,0.21352 0.04618,0.32073 0.01366,0.10721 0.03365,0.21519 0.08049,0.31259 0.06607,0.1374 0.181462,0.24554 0.253328,0.38 0.06308,0.11802 0.09009,0.25127 0.126667,0.37999 0.06224,0.219 0.153684,0.42862 0.25333,0.63333 0.04132,0.0849 0.0841,0.16906 0.126664,0.25333 0.127699,0.25281 0.253536,0.50656 0.379995,0.75999 0.04215,0.0845 0.08437,0.16892 0.126666,0.25333" />
    <path d="m 85.118936,125.39844 c -0.06068,2.03857 -0.272562,4.07261 -0.633325,6.07992 -0.137766,0.76654 -0.297359,1.5298 -0.506658,2.27997 -0.355504,1.2742 -0.853727,2.50843 -1.139987,3.79995 -0.0754,0.34018 -0.136323,0.68512 -0.25333,1.01332 -0.108007,0.30296 -0.26231,0.58733 -0.379995,0.88666 -0.09772,0.24856 -0.169766,0.50631 -0.25333,0.75999 -0.189591,0.57554 -0.439684,1.13226 -0.759992,1.64665 -0.13021,0.20911 -0.272285,0.41178 -0.379995,0.63332 -0.233813,0.48091 -0.295545,1.02869 -0.506661,1.51998 -0.209084,0.48656 -0.558545,0.90354 -0.759989,1.39332 -0.101604,0.24703 -0.16373,0.50835 -0.253331,0.75999 -0.177959,0.49978 -0.461703,0.9546 -0.759989,1.39332 -0.171206,0.25181 -0.348073,0.50004 -0.506661,0.75998 -0.491956,0.80637 -0.800128,1.71197 -1.266651,2.53331 -0.07529,0.13256 -0.155084,0.26342 -0.25333,0.37999 -0.107113,0.12709 -0.234513,0.23529 -0.35132,0.35354 -0.116806,0.11825 -0.225219,0.25024 -0.282005,0.40645 -0.04576,0.12588 -0.0573,0.26542 -0.126667,0.38 -0.06213,0.10263 -0.163641,0.17365 -0.253328,0.25333 -0.04466,0.0397 -0.08689,0.0821 -0.126667,0.12666 -0.101679,0.11397 -0.187234,0.24231 -0.25333,0.38" />
    <path d="m 75.492392,115.77189 c 2.02333,0.13423 4.052759,0.17651 6.079924,0.12666 1.274706,-0.0314 2.55596,-0.10009 3.799951,-0.37999 2.239532,-0.5039 4.263588,-1.66704 6.333254,-2.65997 0.919977,-0.44136 1.854678,-0.85117 2.786632,-1.26665 0.538219,-0.23994 1.085698,-0.48835 1.519981,-0.88666 0.176052,-0.16147 0.330625,-0.34517 0.506661,-0.50666 0.4494,-0.41226 1.019999,-0.66413 1.519981,-1.01332 0.515369,-0.35993 0.951083,-0.8199 1.393317,-1.26665 0.168026,-0.16974 0.337517,-0.33803 0.506658,-0.50666 0.211429,-0.21079 0.422309,-0.42213 0.633329,-0.63332 0.12661,-0.12672 0.25328,-0.25338 0.37999,-0.38" />
"""

_STROKE_ATTRS = 'stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"'

## Favicon: figure in white on the rounded indigo tile.
FAVICON_SVG = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="25 55 120 120">
  <rect x="25" y="55" width="120" height="120" rx="22" fill="#6366f1"/>
  <g fill="none" stroke="#ffffff" {_STROKE_ATTRS}>
{FIGURE_PATHS}  </g>
</svg>
"""
FAVICON_DATA_URI = "data:image/svg+xml;base64," + base64.b64encode(
    FAVICON_SVG.encode("utf-8")
).decode("ascii")

## Same figure for the page header: no tile, inherits the heading colour.
HEADER_GUY_SVG = f"""<svg class="guy" viewBox="60 55 55 105" aria-hidden="true">
  <g fill="none" stroke="currentColor" {_STROKE_ATTRS}>
{FIGURE_PATHS}  </g>
</svg>"""


def _get_build_id() -> str:
    """
    Derives a build identifier from the current git state instead of a
    manually-maintained counter, since that's easy to forget to bump: short
    commit hash plus the generation timestamp.
    """
    repo_dir = Path(__file__).parent
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=repo_dir,
            text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        commit = "unknown"

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"{commit} · {generated_at}"


TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{title}</title>
<link rel="icon" href="{favicon}">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  :root {{
    --bg: #f7f7f8;
    --card: #ffffff;
    --text: #1a1a1e;
    --muted: #6b7280;
    --border: #e5e7eb;
    --accent: #6366f1;
    --accent-weak: #eef0fe;
    --row-hover: #f3f4f6;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bg: #0f1115;
      --card: #171a21;
      --text: #e6e7eb;
      --muted: #9aa0ab;
      --border: #2a2e37;
      --accent: #818cf8;
      --accent-weak: #23263a;
      --row-hover: #1d212b;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0;
    font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
    background: var(--bg);
    color: var(--text);
  }}
  header {{
    padding: 2rem 1.5rem 1rem;
    max-width: 1100px;
    margin: 0 auto;
  }}
  h1 {{
    margin: 0 0 .25rem;
    font-size: 1.5rem;
    letter-spacing: -0.01em;
    display: flex;
    align-items: center;
    gap: .6rem;
  }}
  h1 .guy {{
    height: 1.9em;
    width: auto;
    flex: none;
    color: #6366f1;
  }}
  .subtitle {{
    color: var(--muted);
    font-size: .9rem;
    margin-bottom: 1.25rem;
  }}
  .controls {{
    display: flex;
    flex-direction: column;
    margin-bottom: .5rem;
  }}
  input[type="search"], select {{
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: .55rem .75rem;
    font-size: .9rem;
    outline: none;
  }}
  input[type="search"] {{
    flex: 1;
    min-width: 220px;
  }}
  input[type="search"]:focus, select:focus {{
    border-color: var(--accent);
  }}
  .search-row {{
    display: flex;
    gap: .75rem;
    margin-bottom: .5rem;
  }}
  .filter-toggle {{
    display: flex;
    align-items: center;
    gap: .4rem;
    background: var(--card);
    border: 1px solid var(--border);
    color: var(--text);
    border-radius: 8px;
    padding: .55rem .9rem;
    font-size: .9rem;
    cursor: pointer;
    white-space: nowrap;
  }}
  .filter-toggle:hover {{ border-color: var(--accent); }}
  .filter-toggle.active {{ border-color: var(--accent); color: var(--accent); }}
  .filter-toggle .badge-count {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.2rem;
    height: 1.2rem;
    padding: 0 .3rem;
    border-radius: 999px;
    background: var(--accent);
    color: #fff;
    font-size: .7rem;
    font-weight: 600;
  }}
  .filter-panel {{
    display: none;
    flex-wrap: wrap;
    gap: .75rem;
    margin-bottom: .75rem;
    padding: .75rem;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 8px;
  }}
  .filter-panel.open {{ display: flex; }}
  .filter-field {{
    display: flex;
    flex-direction: column;
    gap: .3rem;
  }}
  .filter-field label {{
    font-size: .7rem;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: var(--muted);
  }}
  .filter-field-range {{
    min-width: 220px;
    flex: 1;
  }}
  .filter-field-range label {{
    display: flex;
    justify-content: space-between;
  }}
  #yearRangeLabel {{
    text-transform: none;
    letter-spacing: 0;
    font-weight: 600;
    color: var(--text);
  }}
  .range-slider {{
    position: relative;
    height: 1.5rem;
    display: flex;
    align-items: center;
  }}
  .range-slider-track, .range-slider-fill {{
    position: absolute;
    left: 0;
    right: 0;
    height: 4px;
    border-radius: 999px;
  }}
  .range-slider-track {{ background: var(--border); }}
  .range-slider-fill {{ background: var(--accent); }}
  .range-slider input[type="range"] {{
    position: absolute;
    left: 0;
    right: 0;
    width: 100%;
    margin: 0;
    background: none;
    pointer-events: none;
    appearance: none;
    -webkit-appearance: none;
  }}
  .range-slider input[type="range"]::-webkit-slider-runnable-track {{
    -webkit-appearance: none;
    background: none;
  }}
  .range-slider input[type="range"]::-webkit-slider-thumb {{
    -webkit-appearance: none;
    pointer-events: auto;
    width: 16px;
    height: 16px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--card);
    box-shadow: 0 0 0 1px var(--accent);
    cursor: pointer;
    margin-top: 0;
  }}
  .range-slider input[type="range"]::-moz-range-track {{
    background: none;
    border: none;
  }}
  .range-slider input[type="range"]::-moz-range-thumb {{
    pointer-events: auto;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--accent);
    border: 2px solid var(--card);
    box-shadow: 0 0 0 1px var(--accent);
    cursor: pointer;
  }}
  main {{
    max-width: 1100px;
    margin: 0 auto 3rem;
    padding: 0 1.5rem;
  }}
  .count {{
    color: var(--muted);
    font-size: .8rem;
    margin: .5rem 0 .75rem;
  }}
  .build-id {{
    color: var(--muted);
    font-size: .7rem;
    font-weight: 400;
    font-family: ui-monospace, "SF Mono", Consolas, monospace;
    opacity: .6;
    margin-left: auto;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    overflow: hidden;
  }}
  table {{
    width: 100%;
    border-collapse: collapse;
    table-layout: fixed;
  }}
  thead th {{
    position: sticky;
    top: 0;
    background: var(--card);
    text-align: left;
    font-size: .75rem;
    text-transform: uppercase;
    letter-spacing: .04em;
    color: var(--muted);
    padding: .75rem 1rem;
    border-bottom: 1px solid var(--border);
    cursor: pointer;
    user-select: none;
    white-space: nowrap;
  }}
  thead th:hover {{ color: var(--text); }}
  thead th.active {{ color: var(--accent); }}
  th.col-meta {{ width: 11rem; }}
  th.col-thema {{ width: 40%; }}
  th.col-link {{ width: 5rem; }}
  tbody td {{
    padding: .8rem 1rem;
    border-bottom: 1px solid var(--border);
    vertical-align: top;
    font-size: .9rem;
    line-height: 1.4;
    overflow-wrap: break-word;
  }}
  tbody tr:last-child td {{ border-bottom: none; }}
  tbody tr:hover {{ background: var(--row-hover); }}
  td.meta {{ white-space: nowrap; }}
  .meta-wrap {{
    display: flex;
    flex-direction: column;
    gap: .3rem;
  }}
  .meta-line {{
    color: var(--muted);
    font-size: .8rem;
  }}
  td.factsheet {{ color: var(--muted); }}
  a.link {{
    color: var(--muted);
    text-decoration: none;
    font-size: .8rem;
  }}
  a.link:hover {{ color: var(--accent); text-decoration: underline; }}
  .empty {{
    text-align: center;
    color: var(--muted);
    padding: 3rem 1rem;
  }}
  .badge {{
    display: inline-block;
    background: var(--accent-weak);
    color: var(--accent);
    border-radius: 999px;
    padding: .1rem .6rem;
    font-size: .75rem;
    font-weight: 600;
  }}
  .badge-format {{
    background: var(--muted);
    color: var(--card);
  }}
  .badge-tournament {{
    display: block;
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }}
  @media (orientation: portrait) {{
    th.col-thema, th.col-factsheet {{ width: 50%; }}
    th.col-meta, th.col-link,
    td.col-meta, td.col-link {{
      display: none;
    }}
    .filter-field-range {{
      max-width: none;
      flex-basis: 100%;
    }}
  }}
  footer {{
    max-width: 1100px;
    margin: 0 auto 2rem;
    padding: 0 1.5rem;
    text-align: center;
  }}
  footer button {{
    background: none;
    border: none;
    color: var(--muted);
    font-size: .8rem;
    text-decoration: underline;
    cursor: pointer;
    padding: 0;
    font-family: inherit;
  }}
  footer button:hover {{ color: var(--accent); }}
  footer a.repo-link {{
    color: var(--muted);
    font-size: .8rem;
    text-decoration: underline;
  }}
  footer a.repo-link:hover {{ color: var(--accent); }}
  footer .footer-sep {{
    color: var(--muted);
    font-size: .8rem;
    margin: 0 .5rem;
  }}
  .modal-overlay {{
    display: none;
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, .5);
    align-items: center;
    justify-content: center;
    padding: 1.5rem;
    z-index: 10;
  }}
  .modal-overlay.open {{ display: flex; }}
  .modal {{
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: 12px;
    max-width: 420px;
    width: 100%;
    padding: 1.5rem;
  }}
  .modal h2 {{
    margin: 0 0 1rem;
    font-size: 1.1rem;
  }}
  .modal p {{
    margin: 0 0 .75rem;
    font-size: .9rem;
    line-height: 1.5;
  }}
  .modal button {{
    margin-top: .5rem;
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 8px;
    padding: .5rem 1rem;
    font-size: .85rem;
    cursor: pointer;
  }}
</style>
</head>
<body>
<header>
  <h1>{guy}{title} <span class="build-id" title="Git commit + generation time">{build_id}</span></h1>
  <div class="controls">
    <div class="search-row">
      <input type="search" id="search" placeholder="Suche in Thema, Factsheet, Runde...">
      <button type="button" class="filter-toggle" id="filterToggle">
        Filter <span class="badge-count" id="filterCount" style="display:none;">0</span>
      </button>
    </div>
    <div class="filter-panel" id="filterPanel">
      <div class="filter-field filter-field-range">
        <label>Zeitraum <span id="yearRangeLabel"></span></label>
        <div class="range-slider" id="yearRangeSlider">
          <div class="range-slider-track"></div>
          <div class="range-slider-fill" id="yearRangeFill"></div>
          <input type="range" id="yearFromFilter">
          <input type="range" id="yearToFilter">
        </div>
      </div>
      <div class="filter-field">
        <label for="formatFilter">Format</label>
        <select id="formatFilter"><option value="">Alle Formate</option></select>
      </div>
      <div class="filter-field">
        <label for="infoslideFilter">Infoslide</label>
        <select id="infoslideFilter">
          <option value="">Egal</option>
          <option value="mit">Mit Infoslide</option>
          <option value="ohne">Ohne Infoslide</option>
        </select>
      </div>
      <div class="filter-field">
        <label for="outroundFilter">Outround</label>
        <select id="outroundFilter">
          <option value="">Egal</option>
          <option value="ja">Ja</option>
          <option value="nein">Nein</option>
        </select>
      </div>
    </div>
  </div>
  <div class="count" id="resultCount"></div>
</header>
<main>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th class="col-meta" data-key="Datum">Datum / Infos</th>
          <th class="col-thema" data-key="Thema">Thema</th>
          <th class="col-factsheet" data-key="Factsheet">Factsheet</th>
          <th class="col-link" data-key="Link">Quelle</th>
        </tr>
      </thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="empty" id="emptyState" style="display:none;">Keine Treffer.</div>
  </div>
</main>

<footer>
  <button type="button" id="impressumBtn">Impressum</button>
  <span class="footer-sep">·</span>
  <a class="repo-link" href="https://github.com/JKRPP/achte_minute_scraper" target="_blank" rel="noopener">GitHub</a>
</footer>

<div class="modal-overlay" id="impressumOverlay">
  <div class="modal">
    <h2>Impressum</h2>
    <p>Jonathan Krapp<br>Scheibenstr. 4<br>52070 Aachen</p>
    <p>Kontakt: <a class="link" href="mailto:themen@krapp.io">themen@krapp.io</a></p>
    <button type="button" id="impressumClose">Schließen</button>
  </div>
</div>

<script>
const DATA = {data_json};

const rowsEl = document.getElementById('rows');
const searchEl = document.getElementById('search');
const yearFromEl = document.getElementById('yearFromFilter');
const yearToEl = document.getElementById('yearToFilter');
const yearRangeFillEl = document.getElementById('yearRangeFill');
const yearRangeLabelEl = document.getElementById('yearRangeLabel');
const formatEl = document.getElementById('formatFilter');
const infoslideEl = document.getElementById('infoslideFilter');
const outroundEl = document.getElementById('outroundFilter');
const countEl = document.getElementById('resultCount');
const emptyEl = document.getElementById('emptyState');
const filterToggle = document.getElementById('filterToggle');
const filterPanel = document.getElementById('filterPanel');
const filterCount = document.getElementById('filterCount');

let sortKey = 'Datum';
let sortDir = -1;

const yearValues = [...new Set(DATA.map(d => (d.Datum ?? '').slice(0, 4)))]
  .filter(Boolean).map(Number).sort((a, b) => a - b);
const yearMin = yearValues[0] ?? 0;
const yearMax = yearValues[yearValues.length - 1] ?? 0;
for (const el of [yearFromEl, yearToEl]) {{
  el.min = yearMin;
  el.max = yearMax;
  el.step = 1;
}}
yearFromEl.value = yearMin;
yearToEl.value = yearMax;

function updateYearRangeUi() {{
  let from = Number(yearFromEl.value);
  let to = Number(yearToEl.value);
  if (from > to) {{
    [from, to] = [to, from];
    yearFromEl.value = from;
    yearToEl.value = to;
  }}
  const span = (yearMax - yearMin) || 1;
  const fromPct = ((from - yearMin) / span) * 100;
  const toPct = ((to - yearMin) / span) * 100;
  yearRangeFillEl.style.left = `${{fromPct}}%`;
  yearRangeFillEl.style.right = `${{100 - toPct}}%`;
  yearRangeLabelEl.textContent = from === to ? `${{from}}` : `${{from}}–${{to}}`;
}}
updateYearRangeUi();

const formatValues = [...new Set(DATA.map(d => d.Format ?? ''))]
  .filter(Boolean).sort();
for (const f of formatValues) {{
  const opt = document.createElement('option');
  opt.value = f;
  opt.textContent = f;
  formatEl.appendChild(opt);
}}

function escapeHtml(s) {{
  return (s ?? '').toString()
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}}

function normalizeForSearch(s) {{
  return (s ?? '').toString().toLowerCase()
    .replaceAll('ä', 'ae').replaceAll('ö', 'oe').replaceAll('ü', 'ue')
    .replaceAll('ß', 'ss');
}}

const VR_ROUND_RE = /^VR\\s*\\d+$/i;

function isOutround(round) {{
  return !VR_ROUND_RE.test((round ?? '').toString().trim());
}}

function updateFilterUi() {{
  const yearActive = Number(yearFromEl.value) !== yearMin || Number(yearToEl.value) !== yearMax;
  const activeCount = [yearActive, formatEl.value, infoslideEl.value, outroundEl.value]
    .filter(Boolean).length;
  filterCount.style.display = activeCount ? 'inline-flex' : 'none';
  filterCount.textContent = activeCount;
  filterToggle.classList.toggle('active', activeCount > 0);
}}

function render() {{
  const q = normalizeForSearch(searchEl.value.trim());
  updateYearRangeUi();
  const yearFrom = Number(yearFromEl.value);
  const yearTo = Number(yearToEl.value);
  const formatFilter = formatEl.value;
  const infoslideFilter = infoslideEl.value;
  const outroundFilter = outroundEl.value;
  updateFilterUi();

  let filtered = DATA.filter(d => {{
    const year = Number((d.Datum ?? '').slice(0, 4));
    if (year && (year < yearFrom || year > yearTo)) return false;
    if (formatFilter && (d.Format ?? '') !== formatFilter) return false;
    if (outroundFilter) {{
      const outround = isOutround(d.Runde);
      if (outroundFilter === 'ja' && !outround) return false;
      if (outroundFilter === 'nein' && outround) return false;
    }}
    if (infoslideFilter) {{
      const hasInfoslide = (d.Factsheet ?? '').toString().trim() !== '';
      if (infoslideFilter === 'mit' && !hasInfoslide) return false;
      if (infoslideFilter === 'ohne' && hasInfoslide) return false;
    }}
    if (!q) return true;
    return normalizeForSearch(d.Thema).includes(q)
      || normalizeForSearch(d.Factsheet).includes(q)
      || normalizeForSearch(d.Runde).includes(q)
      || normalizeForSearch(d.Format).includes(q)
      || normalizeForSearch(d.Tournament).includes(q);
  }});

  const tieBreakKeys = ['Datum', 'Tournament', 'Runde'].filter(k => k !== sortKey);

  filtered.sort((a, b) => {{
    const va = (a[sortKey] ?? '').toString();
    const vb = (b[sortKey] ?? '').toString();
    const primary = va.localeCompare(vb, 'de') * sortDir;
    if (primary !== 0) return primary;

    for (const key of tieBreakKeys) {{
      const ta = (a[key] ?? '').toString();
      const tb = (b[key] ?? '').toString();
      const cmp = ta.localeCompare(tb, 'de') * sortDir;
      if (cmp !== 0) return cmp;
    }}
    return 0;
  }});

  rowsEl.innerHTML = filtered.map(d => `
    <tr>
      <td class="meta col-meta">
        <div class="meta-wrap">
          <div class="meta-line">${{escapeHtml(d.Datum)}}</div>
          ${{d.Tournament ? `<span class="badge badge-tournament" title="${{escapeHtml(d.Tournament)}}">${{escapeHtml(d.Tournament)}}</span>` : ''}}
          <span class="badge">${{escapeHtml(d.Runde)}}</span>
          <span class="badge badge-format">${{escapeHtml(d.Format)}}</span>
        </div>
      </td>
      <td class="thema">${{escapeHtml(d.Thema)}}</td>
      <td class="factsheet">${{escapeHtml(d.Factsheet)}}</td>
      <td class="col-link"><a class="link" href="${{escapeHtml(d.Link)}}" target="_blank" rel="noopener">Artikel &#8599;</a></td>
    </tr>
  `).join('');

  emptyEl.style.display = filtered.length ? 'none' : 'block';
  countEl.textContent = `${{filtered.length}} von ${{DATA.length}} Themen`;
}}

document.querySelectorAll('thead th').forEach(th => {{
  th.addEventListener('click', () => {{
    const key = th.dataset.key;
    if (sortKey === key) {{
      sortDir *= -1;
    }} else {{
      sortKey = key;
      sortDir = 1;
    }}
    document.querySelectorAll('thead th').forEach(t => t.classList.remove('active'));
    th.classList.add('active');
    render();
  }});
}});

searchEl.addEventListener('input', render);
yearFromEl.addEventListener('input', render);
yearToEl.addEventListener('input', render);
formatEl.addEventListener('change', render);
infoslideEl.addEventListener('change', render);
outroundEl.addEventListener('change', render);
filterToggle.addEventListener('click', () => filterPanel.classList.toggle('open'));

render();

const impressumBtn = document.getElementById('impressumBtn');
const impressumOverlay = document.getElementById('impressumOverlay');
const impressumClose = document.getElementById('impressumClose');

impressumBtn.addEventListener('click', () => impressumOverlay.classList.add('open'));
impressumClose.addEventListener('click', () => impressumOverlay.classList.remove('open'));
impressumOverlay.addEventListener('click', (e) => {{
  if (e.target === impressumOverlay) impressumOverlay.classList.remove('open');
}});
</script>
</body>
</html>
"""


def generate_html(csv_path: Path, html_path: Path) -> None:
    df = pd.read_csv(csv_path)
    df = df[
        [
            c
            for c in (
                "Runde",
                "Format",
                "Thema",
                "Factsheet",
                "Link",
                "Datum",
                "Tournament",
            )
            if c in df.columns
        ]
    ]
    df = df.fillna("")

    records = df.to_dict(orient="records")
    html = TEMPLATE.format(
        title=f"Achte Minute Themen",
        count=len(records),
        source=csv_path.name,
        data_json=json.dumps(records, ensure_ascii=False),
        favicon=FAVICON_DATA_URI,
        guy=HEADER_GUY_SVG,
        build_id=_get_build_id(),
    )
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {len(records)} rows to {html_path}")


if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else "topics.csv"
    csv_path = Path(csv_arg)
    html_path = Path("index.html")
    generate_html(csv_path, html_path)
