from fastapi import FastAPI, UploadFile, File, HTTPException, Form, Request
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse, RedirectResponse, Response
from pathlib import Path
import time
import json

app = FastAPI()

UPLOAD_DIR = Path("cloud_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

APP_NAME = "MixRefresh"


def _find_latest_file(user_id: str | None = None, project_id: str | None = None) -> Path | None:
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
):
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = f"{user_id}__{project_id}__{ts}__{file.filename}"
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
            "created_at": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(dest.stat().st_mtime)
            ),
        }
    )


@app.get("/files")
def list_files(user_id: str | None = None, project_id: str | None = None):
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

    return [
        {
            "name": f.name,
            "modified": time.strftime(
                "%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)
            ),
        }
        for f in files
    ]


@app.get("/latest")
def latest_file(user_id: str | None = None, project_id: str | None = None):
    latest = _find_latest_file(user_id=user_id, project_id=project_id)
    if not latest:
        raise HTTPException(status_code=404, detail="No files found")

    return FileResponse(
        latest,
        media_type="audio/wav",
        filename=latest.name,
    )


@app.get("/latest_meta")
def latest_meta(request: Request, user_id: str | None = None, project_id: str | None = None):
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
        "audio_url": audio_url
    }


@app.get("/player", response_class=HTMLResponse)
def player(user_id: str = "default_user", project_id: str = "default_project"):
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
        "icons": []
    }
    return Response(content=json.dumps(content), media_type="application/manifest+json")


@app.get("/app", response_class=HTMLResponse)
def web_app():
    # Default-Projekt (später machen wir das konfigurierbar)
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
      margin: 0; padding: 24px;
      display: flex; align-items: center; justify-content: center;
      min-height: 100vh; background: #0b0b0f; color: #fff;
    }}
    .card {{
      width: 100%; max-width: 520px;
      background: #151521; border-radius: 18px;
      padding: 20px; box-shadow: 0 10px 30px rgba(0,0,0,.35);
    }}
    h1 {{ margin: 0 0 6px 0; font-size: 22px; }}
    .meta {{ opacity: .75; font-size: 13px; margin-bottom: 16px; word-break: break-word; }}
    button {{
      width: 100%; border: 0; border-radius: 14px;
      padding: 14px 16px; font-size: 16px; font-weight: 600;
      background: #4f7cff; color: white;
    }}
    button:disabled {{ opacity: .6; }}
    audio {{ width: 100%; margin-top: 14px; }}
    .row {{ display:flex; gap:10px; margin-top: 10px; }}
    .row button {{ flex:1; background:#2a2a3a; }}
    .row button.primary {{ background:#4f7cff; }}
    .error {{ color: #ff7b7b; font-size: 13px; margin-top: 10px; white-space: pre-wrap; }}
    .hint {{ opacity:.7; font-size:12px; margin-top:12px; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>{APP_NAME}</h1>
    <div class="meta" id="meta">Lade…</div>

    <button class="primary" id="playBtn">Play latest</button>
    <div class="row">
      <button id="refreshBtn">Refresh info</button>
      <button id="stopBtn">Stop</button>
    </div>

    <audio id="player" controls preload="none"></audio>
    <div class="error" id="err"></div>

    <div class="hint">
      Projekt: <b>{user_id}/{project_id}</b>
    </div>
  </div>

<script>
const USER_ID = {json.dumps(user_id)};
const PROJECT_ID = {json.dumps(project_id)};

const metaEl = document.getElementById("meta");
const errEl = document.getElementById("err");
const player = document.getElementById("player");
const playBtn = document.getElementById("playBtn");
const refreshBtn = document.getElementById("refreshBtn");
const stopBtn = document.getElementById("stopBtn");

async function fetchLatestMeta() {{
  errEl.textContent = "";
  metaEl.textContent = "Lade…";
  const url = `/latest_meta?user_id=${{encodeURIComponent(USER_ID)}}&project_id=${{encodeURIComponent(PROJECT_ID)}}`;
  const res = await fetch(url, {{ cache: "no-store" }});
  if (!res.ok) {{
    const txt = await res.text();
    throw new Error(txt);
  }}
  const j = await res.json();
  metaEl.textContent = `Stand: ${{j.created_at}}\\n${{j.filename}}`;
  return j;
}}

async function refresh() {{
  playBtn.disabled = true;
  refreshBtn.disabled = true;
  try {{
    const j = await fetchLatestMeta();
    player.src = j.audio_url;
  }} catch (e) {{
    errEl.textContent = String(e);
  }} finally {{
    playBtn.disabled = false;
    refreshBtn.disabled = false;
  }}
}}

playBtn.addEventListener("click", async () => {{
  try {{
    if (!player.src) {{
      await refresh();
    }}
    await player.play();
  }} catch (e) {{
    errEl.textContent = String(e);
  }}
}});

refreshBtn.addEventListener("click", refresh);
stopBtn.addEventListener("click", () => {{
  player.pause();
  player.currentTime = 0;
}});

// Auto-load beim Öffnen
refresh();
</script>
</body>
</html>
"""


@app.get("/", response_class=HTMLResponse)
def root():
    # Zentrale Anlaufstelle: Root führt zur "App"
    return RedirectResponse(url="/app")
