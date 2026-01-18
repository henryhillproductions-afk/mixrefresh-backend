# main.py (Backend - FastAPI)
# MixRefresh API: Upload + Latest + Meta + Files + File streaming + Player + PWA (/app)
#
# Features:
# - POST /upload : accepts WAV + user_id + project_id + mode (version|overwrite)
#   + accepts display_name + version_label to build pretty filenames:
#     "Projektname_Version XX.wav" and "(latest)" suffix when overwrite
# - GET /latest : streams latest wav for user/project
# - GET /latest_meta : returns filename, created_at, audio_url
# - GET /files : returns list of versions (name, created_at, audio_url) - newest first
# - GET /file/{filename} : stream a specific wav by filename
# - GET /player : simple HTML player
# - GET /app : PWA app UI (latest + versions list)
# - GET /manifest.webmanifest : PWA manifest
# - GET / : redirect to /app
#
# Notes:
# - Render free tier has non-persistent disk. Uploads may disappear after redeploy/restart.

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import (
    JSONResponse,
    FileResponse,
    HTMLResponse,
    RedirectResponse,
    Response,
)

app = FastAPI()

UPLOAD_DIR = Path("cloud_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

APP_NAME = "MixRefresh"


def _safe_filename_part(s: str) -> str:
    """
    Make a user-provided string safe for filenames and URLs.
    Keeps spaces (nice for readability) but strips illegal/suspicious characters.
    """
    s = (s or "").strip()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r'[\\/:*?"<>|]+', "", s)
    return s


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
    Upload a mix.
    mode=version   -> stores with timestamp (history)
    mode=overwrite -> always overwrites a stable "latest" file for that project
    Also receives display_name/version_label to build pretty filename:
      Projektname_Version XX.wav
      Projektname_Version XX (latest).wav
    Internally we still prefix with user_id/project_id for filtering.
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
            "path": str(dest),
            "user_id": user_id,
            "project_id": project_id,
            "mode": mode,
            "display_name": pretty_project,
            "version_label": pretty_version,
            "created_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(dest.stat().st_mtime)),
        }
    )


@app.get("/latest")
def latest_file(user_id: Optional[str] = None, project_id: Optional[str] = None):
    """
    Streams the most recently modified WAV for user/project.
    """
    latest = _find_latest_file(user_id=user_id, project_id=project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No files found")

    return FileResponse(latest, media_type="audio/wav", filename=latest.name)


@app.get("/latest_meta")
def latest_meta(request: Request, user_id: Optional[str] = None, project_id: Optional[str] = None):
    """
    Returns metadata about the newest mix, including an audio_url to stream it.
    """
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

    return {
        "filename": latest.name,
        "created_at": created_at,
        "audio_url": audio_url,
    }


@app.get("/file/{filename}")
def get_file(filename: str):
    """
    Streams/Downloads a specific WAV from cloud_uploads by filename.
    """
    path = UPLOAD_DIR / filename
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(path, media_type="audio/wav", filename=path.name)


@app.get("/files")
def list_files(request: Request, user_id: Optional[str] = None, project_id: Optional[str] = None, limit: int = 25):
    """
    Lists mix versions (newest first) for a user/project, returning audio_url for each.
    """
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

    # clamp limit
    limit = max(1, min(int(limit), 200))
    files = files[:limit]

    base_url = str(request.base_url).rstrip("/")

    out = []
    for f in files:
        created_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime))
        out.append(
            {
                "name": f.name,
                "created_at": created_at,
                "audio_url": f"{base_url}/file/{f.name}",
            }
        )
    return out


@app.get("/player", response_class=HTMLResponse)
def player(user_id: str = "default_user", project_id: str = "default_project"):
    """
    Simple HTML player for latest.
    """
    return f"""
    <html>
    <head><title>Mix Player</title></head>
    <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h2>Latest Mix for {user_id} / {project_id}</h2>
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
    """
    PWA UI:
    - shows latest_meta
    - lists versions via /files
    - plays selected version via <audio>
    """
    # Default-Projekt (später konfigurierbar)
    user_id = "justin"
    project_id = "default"

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
      max-width: 520px;
      background: #151521;
      border-radius: 18px;
      padding: 20px;
      box-shadow: 0 10px 30px rgba(0,0,0,.35);
    }}

    h1 {{
      margin: 0 0 6px 0;
      font-size: 22px;
    }}

    .meta {{
      opacity: .75;
      font-size: 13px;
      margin-bottom: 14px;
      white-space: pre-wrap;
      word-break: break-word;
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

    button.secondary {{
      background: #2a2a3a;
    }}

    button:disabled {{
      opacity: .6;
    }}

    audio {{
      width: 100%;
      margin-top: 14px;
    }}

    .error {{
      color: #ff7b7b;
      font-size: 13px;
      margin-top: 10px;
      white-space: pre-wrap;
    }}

    .section-title {{
      margin-top: 20px;
      margin-bottom: 6px;
      font-size: 14px;
      opacity: .7;
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

    <button id="playLatest">▶ Play latest mix</button>
    <button class="secondary" id="refresh">↻ Refresh list</button>

    <audio id="player" controls preload="none"></audio>

    <div class="section-title">Versionen</div>
    <div id="versions"></div>

    <div class="error" id="error"></div>

    <div class="hint">
      Projekt: <b>{user_id}/{project_id}</b>
    </div>
  </div>

<script>
const USER_ID = "{user_id}";
const PROJECT_ID = "{project_id}";

const metaEl = document.getElementById("meta");
const errorEl = document.getElementById("error");
const player = document.getElementById("player");
const versionsEl = document.getElementById("versions");

const playLatestBtn = document.getElementById("playLatest");
const refreshBtn = document.getElementById("refresh");

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

function renderVersions(list) {{
  versionsEl.innerHTML = "";
  if (!list.length) {{
    versionsEl.innerHTML = "<div class='meta'>Keine Versionen gefunden.</div>";
    return;
  }}

  for (const v of list) {{
    const btn = document.createElement("button");
    btn.className = "version-btn";
    btn.textContent = `▶ ${{v.created_at}} — ${{v.name}}`;
    btn.onclick = async () => {{
      errorEl.textContent = "";
      player.src = v.audio_url;
      try {{
        await player.play();
      }} catch (e) {{
        errorEl.textContent = String(e);
      }}
    }};
    versionsEl.appendChild(btn);
  }}
}}

async function refreshAll() {{
  errorEl.textContent = "";
  metaEl.textContent = "Lade…";

  try {{
    const meta = await fetchLatestMeta();
    metaEl.textContent = `Stand: ${{meta.created_at}}\\n${{meta.filename}}`;
    player.src = meta.audio_url;

    const versions = await fetchVersions();
    renderVersions(versions);

  }} catch (e) {{
    errorEl.textContent = String(e);
  }}
}}

playLatestBtn.onclick = async () => {{
  try {{
    if (!player.src) await refreshAll();
    await player.play();
  }} catch (e) {{
    errorEl.textContent = String(e);
  }}
}};

refreshBtn.onclick = refreshAll;

// Auto-load beim Öffnen
refreshAll();
</script>

</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def root():
    return RedirectResponse(url="/app")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
