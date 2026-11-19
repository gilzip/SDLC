"""SDLC flow desk: manages the development flow of many projects x sub-modules.

Usage: python server.py [--port 8765] [--host 0.0.0.0] [--data data.xlsx]

Flow per (project, sub-module) cell: Product -> Code Readiness -> AI Dev -> Dev -> QA -> end-to-end check.
Every stage is closed by hand ("complete") by its owner, and only then does the next stage start.
AI Dev runs outside the system; its owner just reports it finished. "back" sends a cell to
the previous stage with a note. Every stage of every cell is assigned to an employee.
All data lives in one Excel workbook (the database); the page polls /api/state.
Sheets: ראשי (colored status matrix), פרויקטים (only the project names), תת מודולים, שיוך (project x module +
stage states + owners), עובדים, הגדרות פרויקט (end-to-end approval and role owners per project), יומן.
Never reset: only a missing file is seeded. Reads/writes are serialized by a thread lock and a lock file.
"""
import argparse, copy, json, os, socket, sys, threading, time, uuid
from contextlib import contextmanager
from openpyxl import Workbook, load_workbook
from openpyxl.styles import PatternFill, Font, Alignment
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
# Employee roles. Each stage has one role; employees of that role are offered for it.
ROLES = [
    {"key": "pm", "name": "מנהל מוצר"},
    {"key": "readiness", "name": "אחראי מוכנות קוד"},
    {"key": "architect", "name": "ארכיטקט"},
    {"key": "dev", "name": "מתכנת"},
    {"key": "qa", "name": "QA"},
]
ROLE_KEYS = [r["key"] for r in ROLES]
STAGES = [
    {"key": "pm", "name": "מנהל מוצר", "role": "pm", "done_label": "סיים איפיון",
     "hint": "מנהל המוצר מסיים את האיפיון"},
    {"key": "readiness", "name": "מוכנות Source Code", "role": "readiness", "done_label": "ה-source code מוכן",
     "hint": "בדיקה שה-source code של הפרויקט מוכן לפני הרצת סוכן ה-AI Dev (גישה, בנייה, סביבה)"},
    {"key": "aidev", "name": "פיתוח AI", "role": "architect", "done_label": "פיתוח ה-AI הסתיים",
     "hint": "הארכיטקט אחראי על הרצת סוכן ה-AI Dev מחוץ למערכת. עדכן כשהוא סיים"},
    {"key": "dev", "name": "מפתח", "role": "dev", "done_label": "הקוד נבדק ותקין",
     "hint": "המתכנת בודק שהקוד שה-AI יצר עובד ותקין לפי הגדרת הצרכים"},
    {"key": "qa", "name": "QA", "role": "qa", "done_label": "QA אישר",
     "hint": "בדיקות QA לתת המודול"},
    {"key": "e2e", "name": "בדיקה קצה לקצה", "role": "qa", "done_label": "המודול נבדק ותקין קצה לקצה",
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


def now():
    """Timestamps are rounded to milliseconds so they survive the trip through Excel exactly."""
    return round(time.time(), 3)


def uid():
    return uuid.uuid4().hex[:8]


def new_project(name, modules=()):
    return {"id": uid(), "name": name, "modules": list(modules), "plog": [], "e2e": False,
            "e2e_by": "", "e2e_ts": 0, "owners": {k: "" for k in ROLE_KEYS}}


def seed():
    mods = [{"id": uid(), "name": n} for n in SEED_MODULES]
    projects = [new_project(n, [m["id"] for m in mods[:k]]) for n, k in SEED_PROJECTS]
    return {"modules": mods, "projects": projects, "employees": [], "cells": {}}


SH_MAIN, SH_PROJECTS, SH_MODULES, SH_ASSIGN, SH_EMP, SH_PSET, SH_LOG = (
    "ראשי", "פרויקטים", "תת מודולים", "שיוך", "עובדים", "הגדרות פרויקט", "יומן")
LEGACY_FLOW = "זרם"  # sheet name used by an earlier version of the file
STATE_HE = {"pend": "ממתין", "run": "בעבודה", "done": "הסתיים"}
STATE_CODE = {v: k for k, v in STATE_HE.items()}
STATE_CODE.update({"סוכן עובד": "run", "ממתין לאישור": "run", "אושר": "done"})  # labels from older files
STATUS_HE = {"todo": "לא התחיל", "run": "בתהליך", "done": "הסתיים"}
FILL = {"todo": "F4B4B4", "run": "A9E6F2", "done": "A6E3BF"}
ROLE_HE = {r["key"]: r["name"] for r in ROLES}
ROLE_CODE = {r["name"]: r["key"] for r in ROLES}
STATUS_COL = "סטטוס"


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


def default_owners(p):
    """Per-stage owners from the project's role defaults."""
    return [p.get("owners", {}).get(s["role"], "") for s in STAGES]


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
            p.setdefault("plog", []).insert(0, {"ts": now(), "m": "אישור הבדיקה קצה לקצה בוטל: תת מודול נפתח מחדש או נוסף"})


_CACHE = {"key": None, "data": None}


def file_key():
    """Identity of the workbook on disk. A change made by anyone (another server process, a person in Excel)
    changes it, which invalidates the cache."""
    try:
        st = os.stat(DATA_PATH)
        return (DATA_PATH, st.st_mtime_ns, st.st_size)
    except FileNotFoundError:
        return None


def load():
    """Reads the workbook. Only a missing file is seeded; any other failure raises, never resets data.
    Parsing is skipped when the file is unchanged since we last read or wrote it (polling is frequent)."""
    key = file_key()
    if key is not None and key == _CACHE["key"]:
        return copy.deepcopy(_CACHE["data"])
    try:
        wb = load_workbook(DATA_PATH)
    except FileNotFoundError:
        d = seed()
        save(d)
        return d
    rows = lambda name: [r for r in wb[name].iter_rows(min_row=2, values_only=True) if r and r[0]] if name in wb.sheetnames else []
    cellv = lambda r, i: (r[i] if len(r) > i and r[i] is not None else "")
    d = {"modules": [{"id": str(r[0]), "name": str(r[1])} for r in rows(SH_MODULES)],
         "employees": [{"name": str(r[0]).strip(), "email": str(r[1] or "").strip(), "role": ROLE_CODE.get(r[2], "pm")}
                       for r in rows(SH_EMP)],
         "projects": [], "cells": {}}

    def owner(v):
        """Owners are stored by employee name. Files from the earlier version stored the email: map it to the name."""
        v = str(v or "").strip()
        if v and not any(e["name"] == v for e in d["employees"]):
            v = next((e["name"] for e in d["employees"] if e["email"].lower() == v.lower()), v)
        return v

    # the projects sheet holds only the projects. The end-to-end approval and the role owners live in
    # "הגדרות פרויקט" (files written before that sheet existed kept them as extra columns on the projects sheet)
    settings_sheet = SH_PSET if SH_PSET in wb.sheetnames else SH_PROJECTS
    sheader = [str(h) for h in next(wb[settings_sheet].iter_rows(max_row=1, values_only=True))] if settings_sheet in wb.sheetnames else []
    role_cols = {r["key"]: next((i for i, h in enumerate(sheader) if h.startswith("ברירת מחדל: " + r["name"] + " (")), None)
                 for r in ROLES}
    settings = {str(r[0]): r for r in rows(settings_sheet)}
    for r in rows(SH_PROJECTS):
        p = new_project(str(r[1]))
        p["id"] = str(r[0])
        sr = settings.get(p["id"], ())
        p.update(e2e=cellv(sr, 2) == E2E_DONE_HE, e2e_by=cellv(sr, 3), e2e_ts=cellv(sr, 4) or 0)
        p["owners"] = {k: owner(cellv(sr, role_cols[k])) if role_cols[k] is not None else "" for k in ROLE_KEYS}
        d["projects"].append(p)
    byid = {p["id"]: p for p in d["projects"]}
    # assignment row: project id, project, module id, module, <stage states>, status, <stage owners>
    sheet = SH_ASSIGN if SH_ASSIGN in wb.sheetnames else LEGACY_FLOW
    header = next(wb[sheet].iter_rows(max_row=1, values_only=True)) if sheet in wb.sheetnames else ()
    names = [str(h) for h in header]
    stage_cols = [names.index(s["name"]) if s["name"] in names else None for s in STAGES]
    owner_cols = [next((i for i, h in enumerate(names) if h.startswith("אחראי: " + s["name"] + " (")), None) for s in STAGES]
    for r in rows(sheet):
        pid, mid = str(r[0]), str(r[2])
        if pid in byid and mid not in byid[pid]["modules"]:
            byid[pid]["modules"].append(mid)
            st = [STATE_CODE.get(r[c], "pend") if c is not None else None for c in stage_cols]
            # a stage added after the file was written counts as passed when later stages already started
            for i in range(N):
                if st[i] is None:
                    st[i] = "done" if any(x not in (None, "pend") for x in st[i + 1:]) else "pend"
            # older files had 4 stages: if everything before the first open stage is done, that stage is in progress
            first = next((i for i, s in enumerate(st) if s != "done"), None)
            if first is not None and first > 0 and st[first] == "pend":
                st[first] = "run"
            owners = [owner(cellv(r, c)) if c is not None else None for c in owner_cols]
            fallback = default_owners(byid[pid])
            owners = [fallback[i] if o is None or (not any(owners)) else o for i, o in enumerate(owners)]
            d["cells"][pid + ":" + mid] = {"stages": st, "log": [], "owners": owners}
    for r in rows(SH_LOG):
        entry = {"ts": float(r[2]), "m": str(r[3])}
        if str(r[1]) == "*":  # project-level entry
            if str(r[0]) in byid:
                byid[str(r[0])]["plog"].append(entry)
            continue
        c = d["cells"].get(str(r[0]) + ":" + str(r[1]))
        if c is not None:
            c["log"].append(entry)
    _CACHE["key"], _CACHE["data"] = key, copy.deepcopy(d)
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
                c = d["cells"].get(p["id"] + ":" + m["id"], {"stages": ["pend"] * N})
                st = c["stages"]
                status = status_of(st)
                cur = next((i for i, s in enumerate(st) if s == "run"), None)
                if cur is None:
                    row.append(STATUS_HE[status])
                else:
                    owner = (c.get("owners") or default_owners(p))[cur]
                    row.append("%s: %s%s" % (STAGES[cur]["name"], STATE_HE[st[cur]], " (%s)" % owner if owner else ""))
                fills.append(FILL[status])
            else:
                row.append("")
                fills.append(None)
        e2e, n_done, n_all = project_e2e(d, p)
        row.append({"na": "", "todo": "ממתין לסיום תתי המודולים (%d/%d)" % (n_done, n_all),
                    "run": "ממתין לבדיקה קצה לקצה", "done": "מאושר לפרודקשיין"}[e2e])
        fills.append({"na": None, "todo": FILL["todo"], "run": FILL["run"], "done": FILL["done"]}[e2e])
        ws.append(row)
        for i, f in enumerate(fills):
            if f:
                c = ws.cell(row=ws.max_row, column=i + 2)
                c.fill = PatternFill("solid", fgColor=f)
                c.alignment = Alignment(horizontal="center")
    ws.append([])
    ws.append(["גיליון תצוגה בלבד, מתעדכן אוטומטית מהנתונים. הנתונים עצמם נשמרים בגיליונות פרויקטים, תת מודולים, שיוך, עובדים, הגדרות פרויקט ויומן ולא נמחקים."])
    ws.append(["לעריכה ידנית יש לערוך את הגיליונות האלה ולא את הגיליון הזה."])

    ws = fresh(wb, SH_PROJECTS, ["מזהה", "שם"], 1)
    for p in d["projects"]:
        ws.append([p["id"], p["name"]])
    ws = fresh(wb, SH_MODULES, ["מזהה", "שם"], 2)
    for m in d["modules"]:
        ws.append([m["id"], m["name"]])
    ws = fresh(wb, SH_ASSIGN, ["מזהה פרויקט", "פרויקט", "מזהה תת מודול", "תת מודול"] + [s["name"] for s in STAGES]
               + [STATUS_COL] + ["אחראי: " + s["name"] + " (שם עובד)" for s in STAGES], 3)
    ws2 = fresh(wb, SH_EMP, ["שם", "אימייל", "תפקיד"], 4)
    for e in d["employees"]:
        ws2.append([e["name"], e["email"], ROLE_HE[e["role"]]])
    ws3 = fresh(wb, SH_PSET, ["מזהה פרויקט", "פרויקט", "בדיקה קצה לקצה (פרויקט)", "אושר על ידי", "זמן אישור (unix)"]
                + ["ברירת מחדל: " + r["name"] + " (שם עובד)" for r in ROLES], 5)
    for p in d["projects"]:
        ws3.append([p["id"], p["name"], E2E_DONE_HE if p.get("e2e") else "", p.get("e2e_by", ""), p.get("e2e_ts", 0) or ""]
                   + [p.get("owners", {}).get(k, "") for k in ROLE_KEYS])
    lg = fresh(wb, SH_LOG, ["מזהה פרויקט", "מזהה תת מודול", "זמן (unix)", "הודעה", "זמן"], 6)
    for p in d["projects"]:
        for l in p.get("plog", []):
            lg.append([p["id"], "*", l["ts"], l["m"], time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(l["ts"]))])
        for mid in p["modules"]:
            c = d["cells"].get(p["id"] + ":" + mid, {"stages": ["pend"] * N, "log": []})
            ws.append([p["id"], p["name"], mid, mname.get(mid, "")] + [STATE_HE[s] for s in c["stages"]]
                      + [STATUS_HE[status_of(c["stages"])]] + (c.get("owners") or default_owners(p)))
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
        _CACHE["key"], _CACHE["data"] = file_key(), copy.deepcopy(d)
    except OSError:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise PermissionError("workbook locked")


def find_project(d, pid):
    return next(p for p in d["projects"] if p["id"] == pid)


def cell(d, pid, mid):
    c = d["cells"].setdefault(pid + ":" + mid, {"stages": ["pend"] * N, "log": []})
    if not c.get("owners"):
        c["owners"] = default_owners(find_project(d, pid))
    return c


def log(c, msg):
    c["log"].insert(0, {"ts": now(), "m": msg})
    c["log"] = c["log"][:40]


def view(d):
    cells = {}
    byid = {p["id"]: p for p in d["projects"]}
    for p in d["projects"]:
        for mid in p["modules"]:
            c = d["cells"].get(p["id"] + ":" + mid, {"stages": ["pend"] * N, "log": []})
            st = c["stages"]
            cells[p["id"] + ":" + mid] = {"stages": st, "log": c["log"], "status": status_of(st),
                                          "owners": c.get("owners") or default_owners(byid[p["id"]])}
    projects = []
    for p in d["projects"]:
        e2e, n_done, n_all = project_e2e(d, p)
        projects.append({"id": p["id"], "name": p["name"], "modules": p["modules"], "e2e": e2e,
                         "done": n_done, "total": n_all, "e2e_by": p.get("e2e_by", ""),
                         "log": p.get("plog", [])[:12], "owners": p.get("owners", {})})
    return {"stages": STAGES, "roles": ROLES, "employees": d["employees"], "modules": d["modules"],
            "projects": projects, "cells": cells}


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


def employee_of(d, key):
    key = (key or "").strip()
    if key and not any(e["name"] == key for e in d["employees"]):
        raise ValueError("no such employee")
    return key


def replace_owner(d, old, new):
    """Re-point every reference to an employee (task owners, project defaults); new may be empty to clear."""
    for p in d["projects"]:
        for k, v in p.get("owners", {}).items():
            if v == old:
                p["owners"][k] = new
    for c in d["cells"].values():
        c["owners"] = [new if o == old else o for o in c.get("owners", [])]


def handle(d, path, body):
    """Mutates d. Raises ValueError for bad requests, KeyError for unknown paths."""
    name = str(body.get("name", "")).strip()[:80]
    if path == "/api/project":
        if not name:
            raise ValueError("name required")
        d["projects"].append(new_project(name))
    elif path == "/api/project/update":
        p = find_project(d, body["id"])
        if name:
            p["name"] = name
        if "owners" in body:
            # new role defaults apply to every task of the project, overwriting earlier assignments
            for k in ROLE_KEYS:
                if k in body["owners"]:
                    p["owners"][k] = employee_of(d, body["owners"][k])
            for mid in p["modules"]:
                cell(d, p["id"], mid)["owners"] = default_owners(p)
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
    elif path == "/api/employee":
        # employees are identified by name; several employees may share one email
        email = str(body.get("email", "")).strip()
        if not name or "@" not in email or " " in email:
            raise ValueError("שם וכתובת מייל תקינה נדרשים")
        if body.get("role") not in ROLE_KEYS:
            raise ValueError("תפקיד לא תקין")
        if any(e["name"] == name for e in d["employees"]):
            raise ValueError("עובד בשם הזה כבר קיים")
        d["employees"].append({"name": name, "email": email, "role": body["role"]})
    elif path == "/api/employee/update":
        e = next(e for e in d["employees"] if e["name"] == str(body["key"]).strip())
        email = str(body.get("email", e["email"])).strip()
        if "@" not in email or " " in email:
            raise ValueError("כתובת מייל לא תקינה")
        if name and name != e["name"]:
            if any(x["name"] == name for x in d["employees"]):
                raise ValueError("עובד בשם הזה כבר קיים")
            replace_owner(d, e["name"], name)
            e["name"] = name
        e["email"] = email
        if body.get("role") in ROLE_KEYS:
            e["role"] = body["role"]
    elif path == "/api/employee/delete":
        key = str(body["key"]).strip()
        d["employees"] = [e for e in d["employees"] if e["name"] != key]
        replace_owner(d, key, "")
    elif path == "/api/cell/assign":
        pid, mid, stage = body["project"], body["module"], int(body["stage"])
        if not any(p["id"] == pid and mid in p["modules"] for p in d["projects"]) or not 0 <= stage < N:
            raise ValueError("no such task")
        c = cell(d, pid, mid)
        c["owners"][stage] = employee_of(d, body.get("employee", ""))
        log(c, "אחראי לשלב %s: %s" % (STAGES[stage]["name"], c["owners"][stage] or "ללא אחראי"))
    elif path == "/api/cell":
        cell_action(d, body["project"], body["module"], str(body["action"]), int(body.get("stage", 0)),
                    str(body.get("who", ""))[:60], str(body.get("note", ""))[:500])
    elif path == "/api/project/e2e":
        # manual approval that the whole project works end to end across all its sub-modules
        p = find_project(d, body["id"])
        if project_e2e(d, p)[0] != "run":
            raise ValueError("all sub-modules must be finished first")
        who = str(body.get("who", ""))[:60]
        p["e2e"], p["e2e_by"], p["e2e_ts"] = True, who, now()
        p.setdefault("plog", []).insert(0, {"ts": now(), "m": "%sהפרויקט נבדק ותקין קצה לקצה, מאושר להעלאה לפרודקשיין" % ((who + " — ") if who else "")})
    else:
        raise KeyError(path)
    normalize(d)


class FlowServer(ThreadingHTTPServer):
    # the default backlog is 5: a burst of simultaneous users on Windows would get connections refused
    request_queue_size = 128
    daemon_threads = True

    def handle_error(self, request, client_address):
        if isinstance(sys.exc_info()[1], ConnectionError):
            return  # the client went away mid-response; nothing to report
        super().handle_error(request, client_address)


class V6Server(FlowServer):
    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)  # IPv6 only, IPv4 has its own socket
        super().server_bind()


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
            try:
                with LOCK, file_lock():
                    self.send(200, json.dumps(view(load()), ensure_ascii=False))
            except PermissionError:  # workbook held open exclusively (for example by Excel)
                self.send(409, json.dumps({"error": "קובץ האקסל פתוח ונעול. סגור אותו ונסה שוב"}, ensure_ascii=False))
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
    srv = FlowServer((a.host, a.port), Handler)
    # "localhost" resolves to ::1 first on Windows; with an IPv4-only socket every request then waits ~2s
    # before falling back. Listen on the IPv6 twin as well so http://localhost:PORT is instant.
    twin = {"127.0.0.1": "::1", "0.0.0.0": "::"}.get(a.host)
    if twin:
        try:
            threading.Thread(target=V6Server((twin, a.port), Handler).serve_forever, daemon=True).start()
        except OSError:
            pass  # no IPv6 on this machine
    print("SDLC flow desk on http://localhost:%d" % a.port, flush=True)
    srv.serve_forever()
