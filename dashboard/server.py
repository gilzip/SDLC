"""Live SDLC run desk: serves live.html and a JSON view of a feature's .ai/work folder.

Usage: python server.py --repo C:\\vendure\\my-shop --feature back-in-stock-waitlist [--port 8765]

The page polls /api/state. State comes from the real files the agents write, plus
pipeline-state.json (stage statuses and run log, written by sdlc_state.py).
Approve / request-changes clicks are appended to decisions.jsonl in the feature folder.
"""
import argparse, json, os, subprocess, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STAGE_FILES = [
    ["business-requirement.md"],
    ["technical-discovery.md", "epic.md", "stories.md"],
    ["architecture.md"],
    ["implementation.md"],
    ["schema-execution.md"],
    ["review.md"],
]
SKIP_PREFIXES = (".ai/", ".claude/", "Claude outputs/", "node_modules/", "dist/")
SKIP_SUFFIXES = (".sqlite", ".sqlite3", ".log")
MAX_LINES = 400


def rd(path):
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except OSError:
        return None


def git(repo, *args):
    r = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True, encoding="utf-8", errors="replace")
    return r.stdout


def clip(text):
    lines = text.split("\n")
    if len(lines) > MAX_LINES:
        return "\n".join(lines[:MAX_LINES]) + "\n... (%d more lines)" % (len(lines) - MAX_LINES)
    return text


def lang(path):
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return {"ts": "ts", "tsx": "tsx", "js": "js", "json": "json", "md": "md", "graphql": "graphql"}.get(ext, "")


def code_changes(repo):
    """Changed files in the repo as markdown blocks: (path, markdown). Excludes docs, skills and local data."""
    out = []
    for line in git(repo, "status", "--porcelain", "-uall").split("\n"):
        if len(line) < 4:
            continue
        flag, path = line[:2], line[3:].strip().strip('"')
        if path.startswith(SKIP_PREFIXES) or path.endswith(SKIP_SUFFIXES):
            continue
        if "?" in flag or "A" in flag:
            body = rd(os.path.join(repo, path))
            if body is None:
                continue
            out.append((path, "*New file*\n\n```%s\n%s\n```" % (lang(path), clip(body))))
        else:
            diff = git(repo, "diff", "HEAD", "--", path)
            out.append((path, "*Modified file*\n\n```diff\n%s\n```" % clip(diff)))
    return out


def build_state(repo, feature):
    wdir = os.path.join(repo, ".ai", "work", feature)
    state = {}
    raw = rd(os.path.join(wdir, "pipeline-state.json"))
    if raw:
        try:
            state = json.loads(raw)
        except ValueError:
            pass
    state.setdefault("feature", feature)
    state.setdefault("stages", ["pend"] * 6)
    state.setdefault("log", [])
    changes = code_changes(repo)
    stage_files = []
    for i, names in enumerate(STAGE_FILES):
        files = []
        for n in names:
            body = rd(os.path.join(wdir, n))
            if body is not None:
                files.append({"name": n, "md": body})
        if i == 3:
            for path, md in changes:
                if "/migrations/" not in path:
                    files.append({"name": path, "md": md, "code": True})
        if i == 4:
            for path, md in changes:
                if "/migrations/" in path:
                    files.append({"name": path, "md": md, "code": True})
        stage_files.append(files)
    decisions = []
    raw = rd(os.path.join(wdir, "decisions.jsonl")) or ""
    for ln in raw.split("\n"):
        if ln.strip():
            try:
                decisions.append(json.loads(ln))
            except ValueError:
                pass
    state["files"] = stage_files
    state["decisions"] = decisions
    state["changedCount"] = len(changes)
    return state


class Handler(BaseHTTPRequestHandler):
    repo = ""
    feature = ""

    def log_message(self, *a):
        pass

    def send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path in ("/", "/index.html"):
            self.send(200, open(os.path.join(HERE, "live.html"), "rb").read(), "text/html; charset=utf-8")
        elif path == "/api/state":
            self.send(200, json.dumps(build_state(self.repo, self.feature), ensure_ascii=False), "application/json; charset=utf-8")
        else:
            self.send(404, "not found", "text/plain")

    def do_POST(self):
        if self.path != "/api/decision":
            self.send(404, "not found", "text/plain")
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            d = json.loads(self.rfile.read(n) or b"{}")
            stage, action = int(d["stage"]), str(d["action"])
            assert action in ("approve", "changes", "send-back")
        except Exception:
            self.send(400, "bad request", "text/plain")
            return
        rec = {"ts": time.time(), "stage": stage, "action": action, "note": str(d.get("note", ""))[:2000], "via": "dashboard"}
        wdir = os.path.join(self.repo, ".ai", "work", self.feature)
        os.makedirs(wdir, exist_ok=True)
        with open(os.path.join(wdir, "decisions.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        self.send(200, "{}", "application/json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--feature", required=True)
    ap.add_argument("--port", type=int, default=8765)
    a = ap.parse_args()
    Handler.repo, Handler.feature = a.repo, a.feature
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print("SDLC run desk on http://localhost:%d  (feature %s)" % (a.port, a.feature), flush=True)
    srv.serve_forever()
