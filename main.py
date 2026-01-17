from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from pathlib import Path
import time

app = FastAPI()

# Achtung: Auf Render ist das nur temporärer Speicher.
UPLOAD_DIR = Path("cloud_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


@app.post("/upload")
async def upload(
    file: UploadFile = File(...),
    user_id: str = Form("default_user"),
    project_id: str = Form("default_project"),
):
    """
    Nimmt eine WAV-Datei + User/Projekt entgegen und speichert sie auf dem Server.
    Später ersetzen wir das durch echten Object Storage (z.B. S3).
    """
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
    """
    Listet alle Mixes, optional gefiltert nach User/Projekt.
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
    """
    Gibt die neueste WAV-Datei zurück (optional pro User/Projekt).
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

    if not files:
        raise HTTPException(status_code=404, detail="No files found")

    latest = files[0]
    return FileResponse(
        latest,
        media_type="audio/wav",
        filename=latest.name,
    )


@app.get("/player", response_class=HTMLResponse)
def player(user_id: str = "default_user", project_id: str = "default_project"):
    """
    Einfacher Webplayer für den neuesten Mix (für Tests).
    """
    return f"""
    <html>
    <head><title>Mix Player</title></head>
    <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h2>Latest Mix for {user_id} / {project_id}</h2>
        <audio controls style="width:90%">
          <source src="/latest?user_id={user_id}&project_id={project_id}" type="audio/wav">
          Your browser does not support the audio element.
        </audio>
    </body>
    </html>
    """
