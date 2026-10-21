"""Helper the orchestrator uses to publish pipeline progress to the live dashboard.

  python sdlc_state.py --repo R --feature F init "Title"
  python sdlc_state.py --repo R --feature F set <stage 0-5> <pend|run|wait|done|skip|failed|rework> ["log message"]
  python sdlc_state.py --repo R --feature F log "message"
  python sdlc_state.py --repo R --feature F finish
  python sdlc_state.py --repo R --feature F wait <stage>      # blocks until a dashboard decision for that stage arrives
"""
import argparse, datetime, json, os, sys, time

NAMES = ["Business PM", "Technical PM", "Software Architect", "Developer", "DBA", "Reviewer"]
ap = argparse.ArgumentParser()
ap.add_argument("--repo", required=True)
ap.add_argument("--feature", required=True)
ap.add_argument("cmd")
ap.add_argument("args", nargs="*")
a = ap.parse_args()

wdir = os.path.join(a.repo, ".ai", "work", a.feature)
os.makedirs(wdir, exist_ok=True)
sp = os.path.join(wdir, "pipeline-state.json")
dp = os.path.join(wdir, "decisions.jsonl")


def load():
    try:
        with open(sp, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {"feature": a.feature, "title": a.feature, "stages": ["pend"] * 6, "log": [], "done": False}


def save(s):
    tmp = sp + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)
    os.replace(tmp, sp)


def add_log(s, m):
    s["log"].insert(0, {"t": datetime.datetime.now().strftime("%H:%M:%S"), "m": m})
    s["log"] = s["log"][:30]


if a.cmd == "init":
    s = {"feature": a.feature, "title": a.args[0] if a.args else a.feature, "stages": ["pend"] * 6, "log": [], "done": False}
    add_log(s, "Run started")
    if os.path.exists(dp):
        os.remove(dp)
    save(s)
elif a.cmd == "set":
    s = load()
    s["stages"][int(a.args[0])] = a.args[1]
    if len(a.args) > 2:
        add_log(s, a.args[2])
    save(s)
elif a.cmd == "log":
    s = load()
    add_log(s, a.args[0])
    save(s)
elif a.cmd == "finish":
    s = load()
    s["done"] = True
    add_log(s, "Run complete")
    save(s)
elif a.cmd == "wait":
    stage = int(a.args[0])
    seen = 0
    try:
        with open(dp, encoding="utf-8") as f:
            seen = len([l for l in f if l.strip()])
    except OSError:
        pass
    while True:
        try:
            with open(dp, encoding="utf-8") as f:
                rows = [json.loads(l) for l in f if l.strip()]
        except OSError:
            rows = []
        for r in rows[seen:]:
            if r["stage"] == stage:
                st = load()
                if r["action"] == "approve":
                    st["stages"][stage] = "done"
                    add_log(st, "You approved " + NAMES[stage])
                    if stage < 5:
                        st["stages"][stage + 1] = "run"
                        add_log(st, NAMES[stage + 1] + " agent started")
                elif r["action"] == "changes":
                    st["stages"][stage] = "run"
                    add_log(st, "You requested changes on " + NAMES[stage] + ": " + r.get("note", ""))
                elif r["action"] == "send-back":
                    st["stages"][stage] = "failed"
                    st["stages"][3] = "rework"
                    add_log(st, "You sent the FAIL findings back to the Developer")
                save(st)
                print(json.dumps(r, ensure_ascii=False))
                sys.exit(0)
        seen = max(seen, len(rows))
        time.sleep(1)
else:
    sys.exit("unknown command")
