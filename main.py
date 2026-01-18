# main.py (Backend - FastAPI)  ✅ KOMPLETT
# - Upload WAV (mode=version|overwrite) + display_name + version_label
# - Latest + Latest Meta (immer "(latest)" im display_name)
# - Files list (zeigt display_name ohne user__project__ Prefix, latest markiert)
# - Project registry:
#     GET  /projects   -> liefert Projekte mit display_name (für Dropdown)
#     POST /projects   -> Desktop synced Projektliste hierhin
# - PWA /app mit Projekt-Dropdown (zeigt Display-Namen, nutzt project_id intern)

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, RedirectResponse, Response

app = FastAPI()

UPLOAD_DIR = Path("cloud_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

APP_NAME = "MixRefresh"

PROJECTS_FILE_SUFFIX = "__projects.json"


# -----------------------
# Helper functions
# -----------------------
def _safe_filename_part(s: str) -> str:
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    return s


def _display_from_internal_filename(filename: str) -> str:
    """
    Interner Dateiname:
      user__project__TIMESTAMP__Pretty.wav
      user__project__latest__Pretty.wav
    Display im UI:
      Pretty.wav
    """
    parts = filename.split("__", 3)
    if len(parts) == 4:
        return parts[3]
    return filename


def _add_latest_tag(name: str) -> str:
    """Fügt ' (latest)' vor .wav ein, wenn noch nicht enthalten."""
    if " (latest)" in name:
        return name
    if name.lower().endswith(".wav"):
        return name[:-4] + " (latest).wav"
    return name + " (latest)"


def _projects_path(user_id: str) -> Path:
    return UPLOAD_DIR / f"{user_id}{PROJECTS_FILE_SUFFIX}"


def _load_projects(user_id: str) -> dict:
    p = _projects_path(user_id)
    if not p.exists():
        return {"user_id": user_id, "projects": []}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {"user_id": user_id, "projects": []}


def _save_projects(user_id: str, data: dict) -> None:
    p = _projects_path(user_id)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _find_latest_file(user_id: Optional[str] = None, project_id: Optional[str] = None) -> Optional[Path]:
    files = [f for f in UPLOAD_DIR.glob("*.wav")]

    def matches(f: Path) -> bool:
        if not user_id and not project_id:
            return True
        parts = f.name.split("__")
        f_user = parts[0] if len(parts) > 0 else ""
        f_project = parts[1] if len(parts) > 1 else ""
        if user_id and f_user != user_id:
            return False
        if project_id and f_project != project_id:
            return False
        return True

    files = [f for f in files if matches(f)]
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0] if files else None


# -----------------------
# Project registry (for Web App dropdown)
# -----------------------
@app.get("/projects")
def list_projects(user_id: str = "justin"):
    """
    Liefert Projektliste für UI:
      { "user_id": "...", "projects": [ {"project_id":"default","display_name":"Bunt"}, ... ] }
    """
    return _load_projects(user_id)


@app.post("/projects")
def upsert_projects(
    user_id: str = Form(...),
    projects_json: str = Form(...),
):
    """
    Desktop sendet die komplette Projektliste als JSON-String.
    projects_json erwartet:
      {"projects":[{"project_id":"default","display_name":"Bunt"}, ...]}
    """
    try:
        payload = json.loads(projects_json)
        projects = payload.get("projects", [])

        cleaned = []
        for p in projects:
            pid = str(p.get("project_id", "")).strip()
            name = str(p.get("display_name", "")).strip()
            if pid and name:
                cleaned.append({"project_id": pid, "display_name": name})

        data = {"user_id": user_id, "projects": cleaned}
        _save_projects(user_id, data)
        return {"ok": True, "count": len(cleaned)}
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid projects_json: {e}")


# -----------------------
# Upload + Audio APIs
# -----------------------
@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Form("default_user"),
    project_id: str = Form("default_project"),
    mode: str = Form("version"),  # "version" | "overwrite"
    display_name: str = Form(""),
    version_label: str = Form(""),
):
    """
    mode=version   -> stores with timestamp (history)
    mode=overwrite -> overwrites a stable "latest" file for that project

    Pretty filename:
      Projektname_Version XX.wav
      Projektname_Version XX (latest).wav   (when overwrite)

    Internal prefix kept for filtering:
      user__project__...__Pretty.wav
    """
    mode = (mode or "version").strip().lower()
    if mode not in ("version", "overwrite"):
        raise HTTPException(status_code=400, detail="Invalid mode. Use 'version' or 'overwrite'.")

    pretty_project = _safe_filename_part(display_name) or project_id
    pretty_version = _safe_filename_part(version_label) or time.strftime("%Y-%m-%d_%H-%M-%S")

    if mode == "overwrite":
        pretty = f"{pretty_project}_{pretty_version} (latest).wav"
        safe_name = f"{user_id}__{project_id}__latest__{pretty}"
    else:
        ts = time.strftime("%Y-%m-%d_%H-%M-%S")
        pretty = f"{pretty_project}_{pretty_version}.wav"
        safe_name = f"{user_id}__{project_id}__{ts}__{pretty}"

    dest = UPLOAD_DIR / safe_name

    content = await file.read()
    with dest.open("wb") as f:
        f.write(content)

    return JSONResponse(
        {
            "filename": dest.name,
            "display_name": _display_from_internal_filename(dest.name),
            "user_id": user_id,
            "project_id": project_id,
            "mode": mode,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(dest.stat().st_mtime)),
        }
    )


@app.get("/latest")
def latest_file(user_id: Optional[str] = None, project_id: Optional[str] = None):
    latest = _find_latest_file(user_id=user_id, project_id=project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No files found")
    return FileResponse(latest, media_type="audio/wav", filename=latest.name)


@app.get("/latest_meta")
def latest_meta(request: Request, user_id: Optional[str] = None, project_id: Optional[str] = None):
    latest = _find_latest_file(user_id=user_id, project_id=project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No files found")

    created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(latest.stat().st_mtime))
    base_url = str(request.base_url).rstrip("/")

    audio_url = f"{base_url}/latest"
    params = []
    if user_id:
        params.append(f"user_id={user_id}")
    if project_id:
        params.append(f"project_id={project_id}")
    if params:
        audio_url += "?" + "&".join(params)

    display_name = _display_from_internal_filename(latest.name)
    display_name = _add_latest_tag(display_name)  # immer markieren

    return {
        "filename": latest.name,       # intern (Debug)
        "display_name": display_name,  # fürs UI
        "created_at": created_at,
        "audio_url": audio_url,
    }


@app.get("/file/{filename}")
def get_file(filename: str):
    path = UPLOAD_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.get("/files")
def list_files(request: Request, user_id: Optional[str] = None, project_id: Optional[str] = None, limit: int = 25):
    files = [f for f in UPLOAD_DIR.glob("*.wav")]

    def matches(f: Path) -> bool:
        if not user_id and not project_id:
            return True
        parts = f.name.split("__")
        f_user = parts[0] if len(parts) > 0 else ""
        f_project = parts[1] if len(parts) > 1 else ""
        if user_id and f_user != user_id:
            return False
        if project_id and f_project != project_id:
            return False
        return True

    files = [f for f in files if matches(f)]
    files = sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)

    limit = max(1, min(int(limit), 200))
    files = files[:limit]

    base_url = str(request.base_url).rstrip("/")

    out = []
    for idx, f in enumerate(files):
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
        display_name = _display_from_internal_filename(f.name)

        is_latest = idx == 0
        if is_latest:
            display_name = _add_latest_tag(display_name)

        out.append(
            {
                "name": f.name,  # intern
                "display_name": display_name,
                "created_at": created_at,
                "is_latest": is_latest,
                "audio_url": f"{base_url}/file/{f.name}",
            }
        )
    return out


# -----------------------
# Simple player + PWA
# -----------------------
@app.get("/player", response_class=HTMLResponse)
def player(user_id: str = "default_user", project_id: str = "default_project"):
    return f"""
    <html>
    <head><title>Mix Player</title></head>
    <body style="font-family:sans-serif; text-align:center; padding-top:40px;">
      <h2>Latest Mix for {user_id}/{project_id}</h2>
      <audio controls style="width:90%">
        <source src="/latest?user_id={user_id}&project_id={project_id}" type="audio/wav">
      </audio>
    </body>
    </html>
    """


@app.get("/manifest.webmanifest")
def manifest():
    content = {
        "name": APP_NAME,
        "short_name": APP_NAME,
        "start_url": "/app",
        "display": "standalone",
        "background_color": "#0b0b0f",
        "theme_color": "#0b0b0f",
        "icons": [],
    }
    return Response(content=json.dumps(content), media_type="application/manifest+json")


@app.get("/app", response_class=HTMLResponse)
def web_app():
    # Default-User (später konfigurierbar)
    user_id = "justin"
    default_project = "default"

    return f"""
<!doctype html>
<html lang="de">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <meta name="apple-mobile-web-app-capable" content="yes">
  <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
  <meta name="apple-mobile-web-app-title" content="{APP_NAME}">
  <link rel="manifest" href="/manifest.webmanifest">
  <title>{APP_NAME}</title>

  <style>
    body {{
      font-family: -apple-system, system-ui, Segoe UI, Roboto, Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      min-height: 100vh;
      background: #0b0b0f;
      color: #fff;
    }}
    .card {{
      width: 100%;
      max-width: 560px;
      background: #151521;
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,.35);
    }}
    h1 {{ margin: 0 0 6px 0; font-size: 22px; }}
    .meta {{
      opacity: .75;
      font-size: 13px;
      margin-bottom: 10px;
      white-space: pre-wrap;
      word-break: break-word;
    }}
    .section-title {{
      margin-top: 14px;
      margin-bottom: 6px;
      font-size: 14px;
      opacity: .7;
    }}
    select {{
      width: 100%;
      padding: 12px;
      border-radius: 12px;
      border: 0;
      background: #2a2a3a;
      color: white;
      outline: none;
    }}
    button {{
      width: 100%;
      border: 0;
      border-radius: 14px;
      padding: 14px 16px;
      font-size: 16px;
      font-weight: 600;
      background: #4f7cff;
      color: white;
      margin-top: 10px;
    }}
    button.secondary {{ background: #2a2a3a; }}
    button:disabled {{ opacity: .6; }}
    audio {{ width: 100%; margin-top: 14px; }}
    .error {{
      color: #ff7b7b;
      font-size: 13px;
      margin-top: 10px;
      white-space: pre-wrap;
    }}
    .version-btn {{
      background: #1f1f2e;
      font-size: 14px;
      text-align: left;
    }}
    .hint {{
      opacity: .6;
      font-size: 12px;
      margin-top: 12px;
    }}
  </style>
</head>

<body>
  <div class="card">
    <h1>{APP_NAME}</h1>

    <div class="meta" id="meta">Lade…</div>

    <div class="section-title">Projekt</div>
    <select id="projectSelect"></select>

    <button id="playLatest">▶ Play latest mix</button>
    <button class="secondary" id="refresh">↻ Refresh list</button>

    <audio id="player" controls preload="none"></audio>

    <div class="section-title">Versionen</div>
    <div id="versions"></div>

    <div class="error" id="error"></div>

    <div class="hint">
      User: <b>{user_id}</b>
    </div>
  </div>

<script>
const USER_ID = "{user_id}";
let PROJECT_ID = "{default_project}";

const metaEl = document.getElementById("meta");
const errorEl = document.getElementById("error");
const player = document.getElementById("player");
const versionsEl = document.getElementById("versions");
const projectSelect = document.getElementById("projectSelect");

const playLatestBtn = document.getElementById("playLatest");
const refreshBtn = document.getElementById("refresh");

async function fetchProjects() {{
  const res = await fetch(`/projects?user_id=${{encodeURIComponent(USER_ID)}}`, {{ cache: "no-store" }});
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}}

async function fetchLatestMeta() {{
  const res = await fetch(
    `/latest_meta?user_id=${{encodeURIComponent(USER_ID)}}&project_id=${{encodeURIComponent(PROJECT_ID)}}`,
    {{ cache: "no-store" }}
  );
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}}

async function fetchVersions() {{
  const res = await fetch(
    `/files?user_id=${{encodeURIComponent(USER_ID)}}&project_id=${{encodeURIComponent(PROJECT_ID)}}&limit=25`,
    {{ cache: "no-store" }}
  );
  if (!res.ok) throw new Error(await res.text());
  return await res.json();
}}

function renderProjects(projects) {{
  projectSelect.innerHTML = "";
  for (const p of projects) {{
    const opt = document.createElement("option");
    opt.value = p.project_id;           // intern
    opt.textContent = p.display_name;   // sichtbar
    if (p.project_id === PROJECT_ID) opt.selected = true;
    projectSelect.appendChild(opt);
  }}
}}

function renderVersions(list) {{
  versionsEl.innerHTML = "";
  if (!list.length) {{
    versionsEl.innerHTML = "<div class='meta'>Keine Versionen gefunden.</div>";
    return;
  }}

  for (const v of list) {{
    const btn = document.createElement("button");
    btn.className = "version-btn";
    btn.textContent = `▶ ${{v.created_at}} — ${{v.display_name}}`;
    btn.onclick = async () => {{
      errorEl.textContent = "";
      player.src = v.audio_url;
      try {{ await player.play(); }} catch (e) {{ errorEl.textContent = String(e); }}
    }};
    versionsEl.appendChild(btn);
  }}
}}

async function refreshAll() {{
  errorEl.textContent = "";
  metaEl.textContent = "Lade…";

  try {{
    const meta = await fetchLatestMeta();
    metaEl.textContent = `Stand: ${{meta.created_at}}\\n${{meta.display_name}}`;
    player.src = meta.audio_url;

    const versions = await fetchVersions();
    renderVersions(versions);
  }} catch (e) {{
    errorEl.textContent = String(e);
  }}
}}

projectSelect.addEventListener("change", async () => {{
  PROJECT_ID = projectSelect.value;
  await refreshAll();
}});

playLatestBtn.onclick = async () => {{
  try {{
    if (!player.src) await refreshAll();
    await player.play();
  }} catch (e) {{
    errorEl.textContent = String(e);
  }}
}};

refreshBtn.onclick = refreshAll;

(async function init() {{
  try {{
    const p = await fetchProjects();
    const list = (p.projects || []);
    if (list.length) {{
      if (!list.some(x => x.project_id === PROJECT_ID)) PROJECT_ID = list[0].project_id;
      renderProjects(list);
    }} else {{
      renderProjects([{{ project_id: PROJECT_ID, display_name: PROJECT_ID }}]);
    }}
  }} catch (e) {{
    renderProjects([{{ project_id: PROJECT_ID, display_name: PROJECT_ID }}]);
  }}

  await refreshAll();
}})();
</script>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/app")
