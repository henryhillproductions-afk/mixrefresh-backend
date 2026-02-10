from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import time
import json

app = FastAPI()

# Enable CORS for local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

UPLOAD_DIR = Path("cloud_uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

PROJECTS_DIR = Path("projects_store")
PROJECTS_DIR.mkdir(exist_ok=True)

# Mount static files for the web app
STATIC_DIR = Path("static")
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory="static", html=True), name="static")


@app.get("/health")
def health():
    return {"ok": True}


# ---------- helpers ----------
def _latest_any_wav() -> Path:
    files = list(UPLOAD_DIR.glob("*.wav"))
    if not files:
        raise HTTPException(status_code=404, detail="No files uploaded yet")
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files[0]


def _matches_user_project(f: Path, user_id: str | None, project_id: str | None) -> bool:
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


# ---------- endpoints ----------
@app.post("/upload")
async def upload(
    file: UploadFile = File(...),

    # required-ish (client sends them)
    user_id: str = Form("default_user"),
    project_id: str = Form("default_project"),

    # optional (client sends them too)
    mode: str = Form(""),
    display_name: str = Form(""),
    version_label: str = Form(""),
):
    ts = time.strftime("%Y-%m-%d_%H-%M-%S")
    safe_name = f"{user_id}__{project_id}__{ts}__{file.filename}"
    dest = UPLOAD_DIR / safe_name

    try:
        with dest.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to write file: {e}")

    return JSONResponse(
        {
            "filename": dest.name,
            "path": str(dest),
            "user_id": user_id,
            "project_id": project_id,
            "mode": mode,
            "display_name": display_name,
            "version_label": version_label,
            "created_at": time.strftime(
                "%Y-%m-%d %H:%M:%S",
                time.localtime(dest.stat().st_mtime),
            ),
        }
    )


@app.post("/projects")
async def projects(
    user_id: str = Form(...),
    projects_json: str = Form(...),
):
    try:
        payload = json.loads(projects_json)
    except Exception:
        raise HTTPException(status_code=400, detail="projects_json is not valid JSON")

    dest = PROJECTS_DIR / f"{user_id}.json"
    dest.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    return {"ok": True, "user_id": user_id}


@app.get("/projects")
def list_projects(user_id: str | None = None):
    # Simply list all .json files in PROJECTS_DIR
    # In a real app, filtering by user_id would happen here
    project_files = list(PROJECTS_DIR.glob("*.json"))
    
    results = []
    for p in project_files:
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            # If user_id is provided, only return matching projects? 
            # For now, return all to keep it simple as requested
            results.append(data)
        except Exception:
            pass
            
    return results


@app.get("/files")
def list_files(user_id: str | None = None, project_id: str | None = None):
    files = list(UPLOAD_DIR.glob("*.wav"))
    files = [f for f in files if _matches_user_project(f, user_id, project_id)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    return [
        {
            "name": f.name,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(f.stat().st_mtime)),
        }
        for f in files
    ]


@app.get("/latest")
def latest_file(user_id: str | None = None, project_id: str | None = None):
    files = list(UPLOAD_DIR.glob("*.wav"))
    files = [f for f in files if _matches_user_project(f, user_id, project_id)]
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    if not files:
        raise HTTPException(status_code=404, detail="No files found")

    latest = files[0]
    return FileResponse(latest, media_type="audio/wav", filename=latest.name)


@app.get("/uploads/{filename}")
def get_upload(filename: str):
    file_path = UPLOAD_DIR / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(file_path)


@app.get("/latest_any")
def latest_any():
    latest = _latest_any_wav()
    return FileResponse(latest, media_type="audio/wav", filename=latest.name)


@app.get("/", response_class=HTMLResponse)
def root():
    # plays latest uploaded wav globally (no params)
    return """
    <html>
    <head><title>MixRefresh</title></head>
    <body style="font-family: sans-serif; text-align: center; padding-top: 50px;">
        <h2>Latest Upload</h2>
        <p style="opacity:0.7">Plays the newest WAV found on the server</p>
        <audio controls style="width:90%">
          <source src="/latest_any" type="audio/wav">
        </audio>
    </body>
    </html>
    """


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
