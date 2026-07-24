"""
Web front end for Oussama's Dubai Real Estate Toolkit.

Wraps scripts/bayut_scraper.py and scripts/permit_lookup.py behind a
password-protected website. Each request kicks off a background job
(scrape or permit lookup) and the browser polls for progress/logs until
a result file is ready to download.

Configuration (environment variables / server secrets):
    SITE_PASSWORD        required — password to log into this website
    FLASK_SECRET_KEY      required in production — session signing key
    PROSPECTS_USERNAME    prospectsx.com login (falls back to
    PROSPECTS_PASSWORD    scripts/credentials_local.py if unset)
"""

import os
import sys
import threading
import time
import traceback
import uuid
from functools import wraps
from pathlib import Path

from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_file,
    session,
    url_for,
)

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

BASE_DIR = Path(__file__).resolve().parent
OUTPUTS_DIR = BASE_DIR / "outputs"
UPLOADS_DIR = BASE_DIR / "uploads"
OUTPUTS_DIR.mkdir(exist_ok=True)
UPLOADS_DIR.mkdir(exist_ok=True)

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY") or os.urandom(24)

SITE_PASSWORD = os.environ.get("SITE_PASSWORD")

JOBS: dict = {}
JOBS_LOCK = threading.Lock()


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("authed"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if not SITE_PASSWORD:
            error = "Server misconfigured: SITE_PASSWORD is not set."
        elif request.form.get("password") == SITE_PASSWORD:
            session["authed"] = True
            return redirect(url_for("dashboard"))
        else:
            error = "Wrong password."
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def dashboard():
    return render_template("dashboard.html")


def _new_job() -> str:
    job_id = uuid.uuid4().hex[:12]
    with JOBS_LOCK:
        JOBS[job_id] = {"status": "running", "logs": [], "output": None, "error": None, "download_name": None}
    return job_id


def _log(job_id: str, message: str) -> None:
    with JOBS_LOCK:
        if job_id in JOBS:
            JOBS[job_id]["logs"].append(message)
    print(f"[{job_id}] {message}", flush=True)


def _start_watchdog(job_id: str, timeout_seconds: int) -> None:
    """If a job is still 'running' after timeout_seconds, mark it as failed.
    Browser automation can hang indefinitely (e.g. a site silently blackholes
    this server's IP instead of returning an error) with nothing to catch —
    this guarantees the UI always resolves instead of polling forever."""

    def watch():
        time.sleep(timeout_seconds)
        with JOBS_LOCK:
            job = JOBS.get(job_id)
            if job and job["status"] == "running":
                job["status"] = "error"
                job["error"] = (
                    f"No progress after {timeout_seconds}s, so this job was marked as failed. "
                    "This usually means the target site never responded to the server at all "
                    "(e.g. it silently blocks this server's IP) rather than a bug in the job — "
                    "there was nothing to catch as an error."
                )
        _log(job_id, f"Watchdog: no progress after {timeout_seconds}s, marking as failed.")

    threading.Thread(target=watch, daemon=True).start()


@app.route("/scrape", methods=["POST"])
@login_required
def start_scrape():
    from bayut_scraper import run_scrape_params

    purpose = request.form.get("purpose", "2")
    location = (request.form.get("location") or "Dubai").strip() or "Dubai"
    bedrooms = request.form.get("bedrooms", "a")
    max_listings_raw = (request.form.get("max_listings") or "").strip()
    max_listings = int(max_listings_raw) if max_listings_raw.isdigit() else None

    job_id = _new_job()
    out_path = str(OUTPUTS_DIR / f"bayut_{job_id}.xlsx")
    download_name = f"bayut_{location.replace(' ', '_').lower()}.xlsx"

    def worker():
        try:
            _log(job_id, f"Starting Bayut scrape for '{location}'...")
            run_scrape_params(purpose, location, bedrooms, max_listings, out_path=out_path)
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["output"] = out_path
                JOBS[job_id]["download_name"] = download_name
            _log(job_id, "Done.")
        except Exception as e:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)
            _log(job_id, f"ERROR: {e}")
            traceback.print_exc()

    threading.Thread(target=worker, daemon=True).start()
    _start_watchdog(job_id, timeout_seconds=180)
    return redirect(url_for("job_status", job_id=job_id))


@app.route("/lookup", methods=["POST"])
@login_required
def start_lookup():
    from permit_lookup import run_lookup

    file = request.files.get("excel_file")
    if not file or file.filename == "":
        flash("Please choose an Excel file.")
        return redirect(url_for("dashboard"))

    sheet = (request.form.get("sheet") or "Listings").strip() or "Listings"
    permit_column = (request.form.get("permit_column") or "L").strip() or "L"

    job_id = _new_job()
    upload_path = str(UPLOADS_DIR / f"{job_id}_{file.filename}")
    file.save(upload_path)

    def worker():
        try:
            _log(job_id, f"Starting permit lookup on {file.filename}...")
            run_lookup(
                upload_path,
                sheet=sheet,
                permit_column=permit_column,
                headless=True,
                interactive=False,
                log=lambda msg: _log(job_id, msg),
            )
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "done"
                JOBS[job_id]["output"] = upload_path
                JOBS[job_id]["download_name"] = file.filename
        except Exception as e:
            with JOBS_LOCK:
                JOBS[job_id]["status"] = "error"
                JOBS[job_id]["error"] = str(e)
            _log(job_id, f"ERROR: {e}")
            traceback.print_exc()

    threading.Thread(target=worker, daemon=True).start()
    _start_watchdog(job_id, timeout_seconds=120)
    return redirect(url_for("job_status", job_id=job_id))


@app.route("/jobs/<job_id>")
@login_required
def job_status(job_id):
    if job_id not in JOBS:
        return "Job not found", 404
    return render_template("job.html", job_id=job_id)


@app.route("/jobs/<job_id>/status")
@login_required
def job_status_json(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "not found"}), 404
    with JOBS_LOCK:
        return jsonify(
            {
                "status": job["status"],
                "logs": job["logs"][-300:],
                "has_output": job["output"] is not None,
                "error": job["error"],
            }
        )


@app.route("/jobs/<job_id>/download")
@login_required
def job_download(job_id):
    job = JOBS.get(job_id)
    if not job or not job["output"]:
        return "Not ready", 404
    return send_file(job["output"], as_attachment=True, download_name=job["download_name"])


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
