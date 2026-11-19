"""SDLC flow desk: manages the development flow of many projects x sub-modules.

Usage: python server.py [--port 8765] [--host 0.0.0.0] [--data data.xlsx]

Flow per (project, sub-module) cell: Product -> AI Dev -> Dev -> QA -> end-to-end check.
Every stage is closed by hand ("complete") by its owner, and only then does the next stage start.
AI Dev runs outside the system; its owner just reports it finished. "back" sends a cell to
the previous stage with a note. All data lives in one Excel workbook (the database); the page polls /api/state.
Sheets: ראשי (colored status matrix), פרויקטים, תת מודולים, שיוך (project x module + stage states), יומן.
Never reset: only a missing file is seeded. Reads/writes are serialized by a thread lock and a lock file.
"""
import argparse, json, os, threading, time, uuid
from contextlib import contextmanager
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
STAGES = [
    {"key": "pm", "name": "מנהל מוצר", "done_label": "סיים איפיון",
     "hint": "מנהל המוצר מסיים את האיפיון"},
    {"key": "aidev", "name": "פיתוח AI", "done_label": "פיתוח ה-AI הסתיים",
     "hint": "סוכן ה-AI Dev רץ מחוץ למערכת. עדכן כשהוא סיים"},
    {"key": "dev", "name": "מפתח", "done_label": "הקוד נבדק ותקין",
     "hint": "המפתח בודק שהקוד שה-AI יצר עובד ותקין"},
    {"key": "qa", "name": "QA", "done_label": "QA אישר",
     "hint": "בדיקות QA לתת המודול"},
    {"key": "e2e", "name": "בדיקה קצה לקצה", "done_label": "המודול נבדק ותקין קצה לקצה",
     "hint": "בדיקת כל השלבים של תת המודול מקצה לקצה"},
]
N = len(STAGES)
LOCK = threading.Lock()
DATA_PATH = os.path.join(HERE, "data.xlsx")

SEED_MODULES = ["קליטת מרשם", "הכנסה לסל", "חלופה גנרית", "סיום ניפוק"]
# project -> number of modules (the first N); smaller projects get only part of the modules
SEED_PROJECTS = [
    ("ירפא", 4), ("פורמידבל", 4), ("כללית", 4), ("מאוחדת", 3), ("לאומית", 3),
    ("יקר", 2), ("משרד הבטחון", 2), ("צה\"ל", 2), ("ממשק לרובוט", 1),
]


def uid():
    return uuid.uuid4().hex[:8]


def seed():
    mods = [{"id": uid(), "name": n} for n in SEED_MODULES]
    projects = [{"id": uid(), "name": n, "modules": [m["id"] for m in mods[:k]]} for n, k in SEED_PROJECTS]
    return {"modules": mods, "projects": projects, "cells": {}}


SH_MAIN, SH_PROJECTS, SH_MODULES, SH_ASSIGN, SH_LOG = "ראשי", "פרויקטים", "תת מודולים", "שיוך", "יומן"
LEGACY_FLOW = "זרם"  # sheet name used by an earlier version of the file
STATE_HE = {"pend": "ממתין", "run": "בעבודה", "done": "הסתיים"}
STATE_CODE = {v: k for k, v in STATE_HE.items()}
STATE_CODE.update({"סוכן עובד": "run", "ממתין לאישור": "run", "אושר": "done"})  # labels from older files
STATUS_HE = {"todo": "לא התחיל", "run": "בתהליך", "done": "הסתיים"}
FILL = {"todo": "F4B4B4", "run": "A9E6F2", "done": "A6E3BF"}


@contextmanager
def file_lock(timeout=15, stale=60):
    """Cross-process lock so several server processes can share one workbook."""
    path = DATA_PATH + ".lock"
    end = time.time() + timeout
    while True:
        try:
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(path) > stale:
                    os.remove(path)
                    continue
            except OSError:
                pass
            if time.time() > end:
                raise PermissionError("lock timeout")
            time.sleep(0.05)
    try:
        yield
    finally:
        try:
            os.remove(path)
        except OSError:
            pass


E2E_DONE_HE = "הסתיים"


def status_of(st):
    return "done" if all(s == "done" for s in st) else "todo" if all(s == "pend" for s in st) else "run"


def project_e2e(d, p):
    """Project-level end-to-end check: opens only when every sub-module of the project is done.
    Returns (status, done_count, total) with status na / todo / run / done."""
    total = len(p["modules"])
    done = sum(1 for m in p["modules"]
               if status_of(d["cells"].get(p["id"] + ":" + m, {"stages": ["pend"] * N})["stages"]) == "done")
    if total == 0:
        return "na", 0, 0
    if done < total:
        return "todo", done, total
    return ("done" if p.get("e2e") else "run"), done, total


def normalize(d):
    """An approval is void as soon as any sub-module of the project is no longer done."""
    for p in d["projects"]:
        if p.get("e2e") and project_e2e(d, p)[0] == "todo":
            p["e2e"] = False
            p.setdefault("plog", []).insert(0, {"ts": time.time(), "m": "אישור הבדיקה קצה לקצה בוטל: תת מודול נפתח מחדש או נוסף"})


def load():
    """Reads the workbook. Only a missing file is seeded; any other failure raises, never resets data."""
    try:
        wb = load_workbook(DATA_PATH)
    except FileNotFoundError:
        d = seed()
        save(d)
        return d
    rows = lambda name: [r for r in wb[name].iter_rows(min_row=2, values_only=True) if r and r[0]] if name in wb.sheetnames else []
    d = {"modules": [{"id": str(r[0]), "name": str(r[1])} for r in rows(SH_MODULES)],
         "projects": [{"id": str(r[0]), "name": str(r[1]), "modules": [], "plog": [],
                       "e2e": len(r) > 2 and r[2] == E2E_DONE_HE, "e2e_by": (r[3] or "") if len(r) > 3 else "",
                       "e2e_ts": (r[4] or 0) if len(r) > 4 else 0} for r in rows(SH_PROJECTS)],
         "cells": {}}
    byid = {p["id"]: p for p in d["projects"]}
    # assignment row: project id, project, module id, module, <stage states>, status
    sheet = SH_ASSIGN if SH_ASSIGN in wb.sheetnames else LEGACY_FLOW
    old_n = min(N, len(next(wb[sheet].iter_rows(max_row=1, values_only=True))) - 5) if sheet in wb.sheetnames else N
    for r in rows(sheet):
        pid, mid = str(r[0]), str(r[2])
        if pid in byid and mid not in byid[pid]["modules"]:
            byid[pid]["modules"].append(mid)
            st = [STATE_CODE.get(r[4 + i], "pend") if i < old_n else "pend" for i in range(N)]
            # older files had 4 stages: if everything before the first open stage is done, that stage is in progress
            first = next((i for i, s in enumerate(st) if s != "done"), None)
            if first is not None and first > 0 and st[first] == "pend":
                st[first] = "run"
            d["cells"][pid + ":" + mid] = {"stages": st, "log": []}
    for r in rows(SH_LOG):
        entry = {"ts": float(r[2]), "m": str(r[3])}
        if str(r[1]) == "*":  # project-level entry
            if str(r[0]) in byid:
                byid[str(r[0])]["plog"].append(entry)
            continue
        c = d["cells"].get(str(r[0]) + ":" + str(r[1]))
        if c is not None:
            c["log"].append(entry)
    return d


def fresh(wb, name, header, idx):
    if name in wb.sheetnames:
        del wb[name]
    ws = wb.create_sheet(name, idx)
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True)
    return ws


def save(d):
    # keep the existing workbook (and any extra sheets people added), rewrite only ours
    try:
        wb = load_workbook(DATA_PATH)
    except FileNotFoundError:
        wb = Workbook()
        wb.remove(wb.active)
    mname = {m["id"]: m["name"] for m in d["modules"]}

    ws = fresh(wb, SH_MAIN, ["פרויקט"] + [m["name"] for m in d["modules"]] + ["בדיקה קצה לקצה (פרויקט)"], 0)
    for p in d["projects"]:
        row = [p["name"]]
        fills = []
        for m in d["modules"]:
            if m["id"] in p["modules"]:
                st = d["cells"].get(p["id"] + ":" + m["id"], {"stages": ["pend"] * N})["stages"]
                status = status_of(st)
                cur = next((i for i, s in enumerate(st) if s == "run"), None)
                row.append(STATUS_HE[status] if cur is None else "%s: %s" % (STAGES[cur]["name"], STATE_HE[st[cur]]))
                fills.append(FILL[status])
            else:
                row.append("")
                fills.append(None)
        e2e, n_done, n_all = project_e2e(d, p)
        row.append({"na": "", "todo": "ממתין לסיום תתי המודולים (%d/%d)" % (n_done, n_all),
                    "run": "ממתין לבדיקה קצה לקצה", "done": "הסתיים"}[e2e])
        fills.append({"na": None, "todo": FILL["todo"], "run": FILL["run"], "done": FILL["done"]}[e2e])
        ws.append(row)
        for i, f in enumerate(fills):
            if f:
                c = ws.cell(row=ws.max_row, column=i + 2)
                c.fill = PatternFill("solid", fgColor=f)
                c.alignment = Alignment(horizontal="center")
    ws.append([])
    ws.append(["גיליון תצוגה בלבד, מתעדכן אוטומטית מהנתונים. הנתונים עצמם נשמרים בגיליונות פרויקטים, תת מודולים, שיוך ויומן ולא נמחקים."])
    ws.append(["לעריכה ידנית יש לערוך את הגיליונות האלה ולא את הגיליון הזה."])

    ws = fresh(wb, SH_PROJECTS, ["מזהה", "שם", "בדיקה קצה לקצה (פרויקט)", "אושר על ידי", "זמן אישור (unix)"], 1)
    for p in d["projects"]:
        ws.append([p["id"], p["name"], E2E_DONE_HE if p.get("e2e") else "", p.get("e2e_by", ""), p.get("e2e_ts", 0) or ""])
    ws = fresh(wb, SH_MODULES, ["מזהה", "שם"], 2)
    for m in d["modules"]:
        ws.append([m["id"], m["name"]])
    ws = fresh(wb, SH_ASSIGN, ["מזהה פרויקט", "פרויקט", "מזהה תת מודול", "תת מודול"] + [s["name"] for s in STAGES] + ["סטטוס"], 3)
    lg = fresh(wb, SH_LOG, ["מזהה פרויקט", "מזהה תת מודול", "זמן (unix)", "הודעה", "זמן"], 4)
    for p in d["projects"]:
        for l in p.get("plog", []):
            lg.append([p["id"], "*", l["ts"], l["m"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(l["ts"]))])
        for mid in p["modules"]:
            c = d["cells"].get(p["id"] + ":" + mid, {"stages": ["pend"] * N, "log": []})
            ws.append([p["id"], p["name"], mid, mname.get(mid, "")] + [STATE_HE[s] for s in c["stages"]] + [STATUS_HE[status_of(c["stages"])]])
            for l in c["log"]:
                lg.append([p["id"], mid, l["ts"], l["m"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(l["ts"]))])
    if LEGACY_FLOW in wb.sheetnames:
        del wb[LEGACY_FLOW]
    for w in wb.worksheets:
        w.sheet_view.rightToLeft = True
        for col in w.columns:
            w.column_dimensions[col[0].column_letter].width = max(12, min(48, max(len(str(c.value or "")) for c in col[:60]) + 2))
    tmp = DATA_PATH + ".tmp"
    try:
        wb.save(tmp)
        os.replace(tmp, DATA_PATH)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise PermissionError("workbook locked")


def cell(d, pid, mid):
    return d["cells"].setdefault(pid + ":" + mid, {"stages": ["pend"] * N, "log": []})


def log(c, msg):
    c["log"].insert(0, {"ts": time.time(), "m": msg})
    c["log"] = c["log"][:40]


def view(d):
    cells = {}
    for p in d["projects"]:
        for mid in p["modules"]:
            c = d["cells"].get(p["id"] + ":" + mid, {"stages": ["pend"] * N, "log": []})
            st = c["stages"]
            status = status_of(st)
            cells[p["id"] + ":" + mid] = {"stages": st, "log": c["log"], "status": status}
    projects = []
    for p in d["projects"]:
        e2e, n_done, n_all = project_e2e(d, p)
        projects.append({"id": p["id"], "name": p["name"], "modules": p["modules"], "e2e": e2e,
                         "done": n_done, "total": n_all, "e2e_by": p.get("e2e_by", ""), "log": p.get("plog", [])[:12]})
    return {"stages": STAGES, "modules": d["modules"], "projects": projects, "cells": cells}


def cell_action(d, pid, mid, action, stage, who, note):
    if not any(p["id"] == pid and mid in p["modules"] for p in d["projects"]):
        raise ValueError("no such cell")
    if not 0 <= stage < N:
        raise ValueError("bad stage")
    c = cell(d, pid, mid)
    st = c["stages"]
    by = (who + " — ") if who else ""
    if action == "start":
        if any(s != "pend" for s in st):
            raise ValueError("already started")
        st[0] = "run"
        log(c, "%sהזרם התחיל, שלב: %s" % (by, STAGES[0]["name"]))
    elif action == "complete":
        # the stage owner confirms by hand; the cell moves on to the next stage
        if st[stage] != "run":
            raise ValueError("stage is not in progress")
        st[stage] = "done"
        log(c, "%s%s" % (by, STAGES[stage]["done_label"]))
        if stage + 1 < N:
            st[stage + 1] = "run"
            log(c, "הועבר לשלב: %s" % STAGES[stage + 1]["name"])
        else:
            log(c, "המודול נבדק ותקין קצה לקצה, הזרם הושלם")
    elif action == "back":
        # a stage owner found a problem: send the cell to the previous stage with a note
        if st[stage] != "run" or stage == 0:
            raise ValueError("cannot send back from this stage")
        st[stage] = "pend"
        st[stage - 1] = "run"
        log(c, "%sהוחזר מ%s ל%s: %s" % (by, STAGES[stage]["name"], STAGES[stage - 1]["name"], note))
    elif action == "reopen":
        # the project-level end-to-end check found a problem in this sub-module: reopen it at a stage
        if status_of(st) != "done":
            raise ValueError("sub-module is not finished")
        for i in range(stage, N):
            st[i] = "run" if i == stage else "pend"
        log(c, "%sנפתח מחדש בשלב %s: %s" % (by, STAGES[stage]["name"], note))
    elif action == "reset":
        c["stages"] = ["pend"] * N
        log(c, "%sהזרם אופס" % by)
    else:
        raise ValueError("unknown action")


def handle(d, path, body):
    """Mutates d. Raises ValueError for bad requests, KeyError for unknown paths."""
    name = str(body.get("name", "")).strip()[:80]
    if path == "/api/project":
        if not name:
            raise ValueError("name required")
        d["projects"].append({"id": uid(), "name": name, "modules": []})
    elif path == "/api/project/update":
        p = next(p for p in d["projects"] if p["id"] == body["id"])
        if name:
            p["name"] = name
        if "modules" in body:
            valid = {m["id"] for m in d["modules"]}
            new = [m for m in d["modules"] if m["id"] in body["modules"]]  # keep module order
            for gone in set(p["modules"]) - {m["id"] for m in new}:
                d["cells"].pop(p["id"] + ":" + gone, None)
            p["modules"] = [m["id"] for m in new if m["id"] in valid]
    elif path == "/api/project/delete":
        d["projects"] = [p for p in d["projects"] if p["id"] != body["id"]]
        d["cells"] = {k: v for k, v in d["cells"].items() if not k.startswith(body["id"] + ":")}
    elif path == "/api/module":
        if not name:
            raise ValueError("name required")
        d["modules"].append({"id": uid(), "name": name})
    elif path == "/api/module/update":
        m = next(m for m in d["modules"] if m["id"] == body["id"])
        if name:
            m["name"] = name
    elif path == "/api/module/delete":
        mid = body["id"]
        d["modules"] = [m for m in d["modules"] if m["id"] != mid]
        for p in d["projects"]:
            if mid in p["modules"]:
                p["modules"].remove(mid)
        d["cells"] = {k: v for k, v in d["cells"].items() if not k.endswith(":" + mid)}
    elif path == "/api/cell":
        cell_action(d, body["project"], body["module"], str(body["action"]), int(body.get("stage", 0)),
                    str(body.get("who", ""))[:60], str(body.get("note", ""))[:500])
    elif path == "/api/project/e2e":
        # manual approval that the whole project works end to end across all its sub-modules
        p = next(p for p in d["projects"] if p["id"] == body["id"])
        if project_e2e(d, p)[0] != "run":
            raise ValueError("all sub-modules must be finished first")
        who = str(body.get("who", ""))[:60]
        p["e2e"], p["e2e_by"], p["e2e_ts"] = True, who, time.time()
        p.setdefault("plog", []).insert(0, {"ts": time.time(), "m": "%sהפרויקט נבדק ותקין קצה לקצה" % ((who + " — ") if who else "")})
    else:
        raise KeyError(path)
    normalize(d)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
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
            with open(os.path.join(HERE, "live.html"), "rb") as f:
                self.send(200, f.read(), "text/html; charset=utf-8")
        elif path == "/api/state":
            with LOCK, file_lock():
                self.send(200, json.dumps(view(load()), ensure_ascii=False))
        else:
            self.send(404, "not found", "text/plain")

    def do_POST(self):
        path = self.path.split("?")[0]
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
            with LOCK, file_lock():
                d = load()
                handle(d, path, body)
                save(d)
            self.send(200, "{}")
        except KeyError:
            self.send(400, json.dumps({"error": "bad request"}))
        except (ValueError, StopIteration, TypeError) as e:
            self.send(400, json.dumps({"error": str(e) or "bad request"}, ensure_ascii=False))
        except PermissionError:
            self.send(409, json.dumps({"error": "קובץ האקסל פתוח ונעול. סגור אותו ונסה שוב"}, ensure_ascii=False))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--data", default=DATA_PATH)
    ap.add_argument("--host", default="127.0.0.1", help="use 0.0.0.0 to let other users on the network connect")
    a = ap.parse_args()
    DATA_PATH = os.path.abspath(a.data)
    srv = ThreadingHTTPServer((a.host, a.port), Handler)
    print("SDLC flow desk on http://localhost:%d" % a.port, flush=True)
    srv.serve_forever()
