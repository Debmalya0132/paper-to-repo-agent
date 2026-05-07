"""
Flask web server — Paper-to-Repo Agent
Supports SSE streaming for real-time progress on generation.
"""

import io, json, uuid, threading
from queue import Queue, Empty
from flask import Flask, render_template, request, jsonify, send_file, Response
from agent import PaperToRepoAgent
import os

app = Flask(__name__)

# In-memory stores for streaming jobs
_job_queues: dict = {}   # job_id -> Queue of SSE events
_job_zips: dict = {}     # job_id -> zip bytes (ready to download)


# ------------------------------------------------------------------ pages
@app.route("/")
def index():
    return render_template("index.html")


# ------------------------------------------------------------------ analyze
@app.route("/api/analyze", methods=["POST"])
def analyze():
    data = request.get_json() or {}
    jd = data.get("job_description", "").strip()
    if not jd:
        return jsonify({"error": "Job description is required"}), 400
    try:
        agent = PaperToRepoAgent()
        areas = agent.extract_research_areas(jd)
        papers = agent.find_papers(areas, jd)
        return jsonify({"papers": papers, "research_areas": areas})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ------------------------------------------------------------------ generate (SSE)
@app.route("/api/generate/start", methods=["POST"])
def generate_start():
    """Kick off async generation. Returns job_id immediately."""
    data = request.get_json() or {}
    paper = data.get("paper")
    if not paper:
        return jsonify({"error": "Paper required"}), 400

    job_id = str(uuid.uuid4())
    q = Queue()
    _job_queues[job_id] = q

    def run():
        try:
            agent = PaperToRepoAgent()

            def cb(msg: str):
                q.put({"type": "progress", "message": msg})

            zip_bytes = agent.generate_zip_bytes(paper, cb=cb)
            _job_zips[job_id] = zip_bytes
            q.put({"type": "done", "job_id": job_id})
        except Exception as ex:
            q.put({"type": "error", "message": str(ex)})

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/generate/stream/<job_id>")
def generate_stream(job_id):
    """SSE endpoint — streams progress events until done/error."""
    q = _job_queues.get(job_id)
    if not q:
        def err():
            yield 'data: {"type":"error","message":"Job not found"}\n\n'
        return Response(err(), mimetype="text/event-stream")

    def event_stream():
        while True:
            try:
                item = q.get(timeout=120)
                yield f"data: {json.dumps(item)}\n\n"
                if item["type"] in ("done", "error"):
                    _job_queues.pop(job_id, None)
                    break
            except Empty:
                yield 'data: {"type":"error","message":"Timeout"}\n\n'
                break

    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.route("/api/download/<job_id>")
def download(job_id):
    """Serve the generated zip for a completed job."""
    zip_bytes = _job_zips.pop(job_id, None)
    if not zip_bytes:
        return jsonify({"error": "Not found or already downloaded"}), 404
    return send_file(
        io.BytesIO(zip_bytes),
        mimetype="application/zip",
        as_attachment=True,
        download_name="implementation.zip",
    )


# ------------------------------------------------------------------ GitHub push
@app.route("/api/github-push", methods=["POST"])
def github_push():
    data = request.get_json() or {}
    paper = data.get("paper")
    job_id = data.get("job_id")
    token = data.get("github_token", "").strip() or os.environ.get("GITHUB_TOKEN", "")
    username = data.get("github_username", "").strip() or os.environ.get("GITHUB_USERNAME", "")

    if not paper or not token or not username:
        return jsonify({"error": "paper, github_token, and github_username are required"}), 400

    # Re-generate (or get from cache) to get the files dict
    try:
        import zipfile as zf, io as _io
        agent = PaperToRepoAgent()

        # Use cached zip if available
        h = agent._paper_hash(paper)
        cached = agent._cache_get(h)
        zip_bytes = cached if cached else agent.generate_zip_bytes(paper)

        # Extract files from zip
        files = {}
        with zf.ZipFile(_io.BytesIO(zip_bytes)) as z:
            for name in z.namelist():
                files[name] = z.read(name).decode("utf-8", errors="replace")

        repo_url = agent.push_to_github(files, paper, token, username)
        return jsonify({"repo_url": repo_url})
    except Exception as ex:
        return jsonify({"error": str(ex)}), 500


# ------------------------------------------------------------------ run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
