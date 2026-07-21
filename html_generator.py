"""
Generates a single self-contained HTML page (searchable/sortable table) from
one of the topics_*.csv files produced by scraping.py.
"""

import json
import sys
from pathlib import Path

import pandas as pd

TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<title>{title}</title>
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
  }}
  .subtitle {{
    color: var(--muted);
    font-size: .9rem;
    margin-bottom: 1.25rem;
  }}
  .controls {{
    display: flex;
    gap: .75rem;
    flex-wrap: wrap;
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
  th.col-datum {{ width: 6rem; }}
  th.col-runde {{ width: 6rem; }}
  th.col-thema {{ width: 36%; }}
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
  td.runde {{
    white-space: nowrap;
    font-weight: 600;
    color: var(--accent);
  }}
  td.datum {{ white-space: nowrap; color: var(--muted); }}
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
  @media (orientation: portrait) {{
    th.col-thema, th.col-factsheet {{ width: 50%; }}
    th.col-datum, th.col-runde, th.col-link,
    td.col-datum, td.col-runde, td.col-link {{
      display: none;
    }}
  }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div class="controls">
    <input type="search" id="search" placeholder="Suche in Thema, Factsheet, Runde...">
    <select id="yearFilter"><option value="">Alle Jahre</option></select>
  </div>
  <div class="count" id="resultCount"></div>
</header>
<main>
  <div class="card">
    <table>
      <thead>
        <tr>
          <th class="col-datum" data-key="Datum">Datum</th>
          <th class="col-runde" data-key="Runde">Runde</th>
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

<script>
const DATA = {data_json};

const rowsEl = document.getElementById('rows');
const searchEl = document.getElementById('search');
const yearEl = document.getElementById('yearFilter');
const countEl = document.getElementById('resultCount');
const emptyEl = document.getElementById('emptyState');

let sortKey = 'Datum';
let sortDir = -1;

const yearValues = [...new Set(DATA.map(d => (d.Datum ?? '').slice(0, 4)))]
  .filter(Boolean).sort().reverse();
for (const y of yearValues) {{
  const opt = document.createElement('option');
  opt.value = y;
  opt.textContent = y;
  yearEl.appendChild(opt);
}}

function escapeHtml(s) {{
  return (s ?? '').toString()
    .replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}}

function render() {{
  const q = searchEl.value.trim().toLowerCase();
  const yearFilter = yearEl.value;

  let filtered = DATA.filter(d => {{
    if (yearFilter && !(d.Datum ?? '').startsWith(yearFilter)) return false;
    if (!q) return true;
    return (d.Thema ?? '').toLowerCase().includes(q)
      || (d.Factsheet ?? '').toLowerCase().includes(q)
      || (d.Runde ?? '').toLowerCase().includes(q);
  }});

  filtered.sort((a, b) => {{
    const va = (a[sortKey] ?? '').toString();
    const vb = (b[sortKey] ?? '').toString();
    return va.localeCompare(vb, 'de') * sortDir;
  }});

  rowsEl.innerHTML = filtered.map(d => `
    <tr>
      <td class="datum col-datum">${{escapeHtml(d.Datum)}}</td>
      <td class="runde col-runde"><span class="badge">${{escapeHtml(d.Runde)}}</span></td>
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
yearEl.addEventListener('change', render);

render();
</script>
</body>
</html>
"""


def generate_html(csv_path: Path, html_path: Path) -> None:
    df = pd.read_csv(csv_path)
    df = df[
        [c for c in ("Runde", "Thema", "Factsheet", "Link", "Datum") if c in df.columns]
    ]
    df = df.fillna("")

    records = df.to_dict(orient="records")
    html = TEMPLATE.format(
        title=f"Achte Minute Themen",
        count=len(records),
        source=csv_path.name,
        data_json=json.dumps(records, ensure_ascii=False),
    )
    html_path.write_text(html, encoding="utf-8")
    print(f"Wrote {len(records)} rows to {html_path}")


if __name__ == "__main__":
    csv_arg = sys.argv[1] if len(sys.argv) > 1 else "topics.csv"
    csv_path = Path(csv_arg)
    html_path = Path("index.html")
    generate_html(csv_path, html_path)
