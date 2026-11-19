"""End-to-end test of the flow desk. Starts its own server on a temp workbook (never touches real data).

Run:  python dashboard/e2e_test.py
"""
import json, os, subprocess, sys, tempfile, threading, time, urllib.request as u
from urllib.error import HTTPError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT = 8791
B = "http://localhost:%d" % PORT
TMP = tempfile.mkdtemp(prefix="flowdesk_")
XLSX = os.path.join(TMP, "e2e.xlsx")
results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail and not cond else ""), flush=True)


def post(path, body):
    try:
        r = u.urlopen(u.Request(B + path, json.dumps(body).encode(), {"Content-Type": "application/json"}))
        return r.status, {}
    except HTTPError as e:
        try:
            return e.code, json.loads(e.read())
        except Exception:
            return e.code, {}


def state():
    return json.load(u.urlopen(B + "/api/state"))


def start_server():
    p = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py"), "--port", str(PORT), "--data", XLSX],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(60):
        try:
            state()
            return p
        except Exception:
            time.sleep(0.2)
    raise SystemExit("server did not start")


def stop(p):
    p.terminate()
    p.wait()


srv = start_server()
try:
    # ---- seed and page
    page = u.urlopen(B + "/").read().decode("utf-8")
    check("page served", "<title>לוח זרימת פיתוח</title>" in page)
    s = state()
    check("seed: 9 projects, 4 sub-modules", len(s["projects"]) == 9 and len(s["modules"]) == 4)
    check("seed: 6 stages in order", [x["key"] for x in s["stages"]] == ["pm", "readiness", "aidev", "dev", "qa", "e2e"])
    check("seed: partial assignment (small project has fewer modules)",
          len({len(p["modules"]) for p in s["projects"]}) > 1 and min(len(p["modules"]) for p in s["projects"]) == 1)
    check("seed: every cell not started", all(c["status"] == "todo" for c in s["cells"].values()))
    check("excel created with all sheets", os.path.exists(XLSX))
    from openpyxl import load_workbook
    sheets = load_workbook(XLSX).sheetnames
    check("excel sheets: main + sub sheets", sheets == ["ראשי", "פרויקטים", "תת מודולים", "שיוך", "עובדים", "הגדרות פרויקט", "יומן"], sheets)
    pws = load_workbook(XLSX)["פרויקטים"]
    check("projects sheet holds only the project list (id, name)", pws.max_column == 2 and
          [r[1] for r in pws.iter_rows(min_row=2, values_only=True)] == ["ירפא", "פורמידבל", "כללית", "מאוחדת", "לאומית", "יקר", "משרד הבטחון", "צה\"ל", "ממשק לרובוט"],
          [r[1] for r in pws.iter_rows(min_row=2, values_only=True)])

    # ---- employees
    emps = [("דרור", "pm"), ("אייל", "readiness"), ("אדיר", "architect"), ("שמעון", "dev"), ("נחום", "qa")]
    check("add 5 employees sharing one email",
          all(post("/api/employee", {"name": n, "email": "giltzip@gmail.com", "role": r})[0] == 200 for n, r in emps))
    check("duplicate employee name rejected", post("/api/employee", {"name": "דרור", "email": "a@b.co", "role": "pm"})[0] == 400)
    check("bad email rejected", post("/api/employee", {"name": "זר", "email": "nope", "role": "pm"})[0] == 400)
    check("bad role rejected", post("/api/employee", {"name": "זר", "email": "a@b.co", "role": "boss"})[0] == 400)

    # ---- project: owners, modules
    P = {p["name"]: p for p in state()["projects"]}
    kal = P["כללית"]
    owners = {"pm": "דרור", "readiness": "אייל", "architect": "אדיר", "dev": "שמעון", "qa": "נחום"}
    check("project role defaults applied", post("/api/project/update", {"id": kal["id"], "owners": owners})[0] == 200)
    s = state()
    cells = [k for k in s["cells"] if k.startswith(kal["id"] + ":")]
    check("defaults copied to every task", all(s["cells"][k]["owners"] == ["דרור", "אייל", "אדיר", "שמעון", "נחום", "נחום"] for k in cells))
    check("unknown owner rejected", post("/api/project/update", {"id": kal["id"], "owners": {"pm": "מישהו"}})[0] == 400)
    mid = kal["modules"]
    check("assign single task override",
          post("/api/cell/assign", {"project": kal["id"], "module": mid[0], "stage": 3, "employee": "נחום"})[0] == 200
          and state()["cells"][kal["id"] + ":" + mid[0]]["owners"][3] == "נחום")

    # ---- full flow for every sub-module of כללית
    def cell(m, action, stage=0, note=""):
        return post("/api/cell", {"project": kal["id"], "module": m, "action": action, "stage": stage, "who": "בודק", "note": note})[0]

    def stages(m):
        return "".join(x[0] for x in state()["cells"][kal["id"] + ":" + m]["stages"])

    check("cannot complete before start", cell(mid[0], "complete", 0) == 400)
    check("start all sub-modules", all(cell(m, "start") == 200 for m in mid))
    check("cannot start twice", cell(mid[0], "start") == 400)
    check("first stage running", stages(mid[0]) == "rppppp", stages(mid[0]))
    check("cannot skip a stage", cell(mid[0], "complete", 2) == 400)
    check("cannot go back from first stage", cell(mid[0], "back", 0, "x") == 400)
    cell(mid[0], "complete", 0)
    check("readiness stage opens after product", stages(mid[0]) == "drpppp", stages(mid[0]))
    check("send back to product", cell(mid[0], "back", 1, "חסר איפיון") == 200 and stages(mid[0]) == "rppppp")
    cell(mid[0], "complete", 0)
    check("progress through to AI dev", cell(mid[0], "complete", 1) == 200 and stages(mid[0]) == "ddrppp")
    check("dev sends back to AI dev", cell(mid[0], "complete", 2) == 200 and cell(mid[0], "back", 3, "תקלה") == 200 and stages(mid[0]) == "ddrppp")
    for m in mid:
        # bring every sub-module up to the last stage except the first, which is checked separately
        pass
    for m in mid[1:]:
        for k in range(6):
            cell(m, "complete", k)
    for k in range(2, 6):
        cell(mid[0], "complete", k)
    check("all stages done in every sub-module", all(stages(m) == "dddddd" for m in mid))
    s = state()
    kp = [p for p in s["projects"] if p["id"] == kal["id"]][0]
    check("project check opens when all sub-modules done", kp["e2e"] == "run" and kp["done"] == kp["total"], kp["e2e"])
    check("other projects still waiting", all(p["e2e"] in ("todo", "na") for p in s["projects"] if p["id"] != kal["id"]))
    check("log recorded who did what", any("בודק" in l["m"] for l in s["cells"][kal["id"] + ":" + mid[0]]["log"]))

    # ---- project-level end-to-end: fail, reopen, pass, production gate
    check("premature approval of another project rejected", post("/api/project/e2e", {"id": P["ירפא"]["id"], "who": "נחום"})[0] == 400)
    check("reopen a sub-module at QA", cell(mid[2], "reopen", 4, "החלופה לא מגיעה לסיום") == 200)
    kp = [p for p in state()["projects"] if p["id"] == kal["id"]][0]
    check("reopen blocks the project check", kp["e2e"] == "todo" and kp["done"] == kp["total"] - 1, kp)
    check("approval rejected while a sub-module is open", post("/api/project/e2e", {"id": kal["id"], "who": "נחום"})[0] == 400)
    cell(mid[2], "complete", 4)
    cell(mid[2], "complete", 5)
    check("project check opens again", [p for p in state()["projects"] if p["id"] == kal["id"]][0]["e2e"] == "run")
    check("QA approves the project", post("/api/project/e2e", {"id": kal["id"], "who": "נחום"})[0] == 200)
    kp = [p for p in state()["projects"] if p["id"] == kal["id"]][0]
    check("project approved for production", kp["e2e"] == "done" and kp["e2e_by"] == "נחום", kp)
    check("approval voided when a sub-module is added",
          post("/api/module", {"name": "דוח יומי"})[0] == 200
          and post("/api/project/update", {"id": kal["id"], "modules": mid + [state()["modules"][-1]["id"]]})[0] == 200
          and [p for p in state()["projects"] if p["id"] == kal["id"]][0]["e2e"] == "todo")

    # ---- persistence: restart the server, state must survive in the workbook
    before = json.dumps(state(), sort_keys=True)
    stop(srv)
    srv = start_server()
    after = json.dumps(state(), sort_keys=True)
    check("state identical after server restart (Excel is the database)", before == after)
    check("workbook not reset on restart", len(state()["employees"]) == 5)
    wb = load_workbook(XLSX)
    main = wb["ראשי"]
    texts = [c.value for row in main.iter_rows(min_row=2, values_only=False) for c in row if c.value]
    check("main sheet shows statuses with colors", any(c.fill.fgColor.rgb not in (None, "00000000") for row in main.iter_rows(min_row=2) for c in row if c.value))
    check("main sheet note says it is display only", any("תצוגה בלבד" in str(t) for t in texts))
    check("employees sheet has name+email+role", [c.value for c in wb["עובדים"][2]] == ["דרור", "giltzip@gmail.com", "pm" if False else "מנהל מוצר"], [c.value for c in wb["עובדים"][2]])

    # ---- employee rename / delete propagate
    check("rename employee", post("/api/employee/update", {"key": "נחום", "name": "נחום כהן", "email": "giltzip@gmail.com", "role": "qa"})[0] == 200)
    s = state()
    check("rename updates all owners", s["cells"][kal["id"] + ":" + mid[0]]["owners"][5] == "נחום כהן" and [p for p in s["projects"] if p["id"] == kal["id"]][0]["owners"]["qa"] == "נחום כהן")
    check("delete employee clears their tasks", post("/api/employee/delete", {"key": "נחום כהן"})[0] == 200
          and state()["cells"][kal["id"] + ":" + mid[0]]["owners"][5] == "")

    # ---- project and module management
    check("add project", post("/api/project", {"name": "פרויקט חדש"})[0] == 200)
    new = [p for p in state()["projects"] if p["name"] == "פרויקט חדש"][0]
    check("assign subset of modules to new project", post("/api/project/update", {"id": new["id"], "modules": state()["modules"][0:2] and [state()["modules"][0]["id"]]})[0] == 200)
    check("rename module updates everywhere", post("/api/module/update", {"id": state()["modules"][0]["id"], "name": "קליטת מרשם (שונה)"})[0] == 200
          and state()["modules"][0]["name"] == "קליטת מרשם (שונה)")
    check("delete module removes its cells", post("/api/module/delete", {"id": mid[3]})[0] == 200
          and not any(k.endswith(":" + mid[3]) for k in state()["cells"]))
    check("delete project", post("/api/project/delete", {"id": new["id"]})[0] == 200 and not any(p["id"] == new["id"] for p in state()["projects"]))
    check("unknown endpoint rejected", post("/api/nope", {})[0] == 400)
    check("malformed request rejected", post("/api/cell", {"project": "x"})[0] == 400)

    # ---- concurrency: many users writing at once, nothing lost
    base = len(state()["projects"])
    res = []
    ts = [threading.Thread(target=lambda i=i: res.append(post("/api/project", {"name": "מקביל %d" % i})[0])) for i in range(15)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("15 parallel writes all succeed and none lost", res.count(200) == 15 and len(state()["projects"]) == base + 15, res)
    ys = state()
    one = ys["projects"][0]
    r2 = []
    tgt = [m for m in one["modules"]][0]
    post("/api/cell", {"project": one["id"], "module": tgt, "action": "start"})
    ts = [threading.Thread(target=lambda: r2.append(post("/api/cell", {"project": one["id"], "module": tgt, "action": "complete", "stage": 0})[0])) for _ in range(5)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("racing approvals: exactly one wins", sorted(r2) == [200, 400, 400, 400, 400], r2)

    # ---- a burst of simultaneous users must not get connections refused (listen backlog)
    burst = []
    one = state()["projects"][0]
    ts = [threading.Thread(target=lambda: burst.append(post("/api/project", {"name": "burst"})[0])) for _ in range(40)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    check("40 simultaneous requests all answered", burst.count(200) == 40, sorted(set(burst)))

    # ---- workbook held open exclusively (like Excel does): clear 409 on read and write, no data loss
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        k.CreateFileW.restype = ctypes.c_void_p
        h = k.CreateFileW(XLSX, 0x80000000 | 0x40000000, 0, None, 3, 0x80, None)  # share mode 0
        try:
            wcode, wbody = post("/api/project", {"name": "בזמן נעילה"})
            try:
                rcode = u.urlopen(B + "/api/state").status
            except HTTPError as e:
                rcode = e.code
        finally:
            k.CloseHandle(ctypes.c_void_p(h))
        check("write while workbook is open gives 409 with a message", wcode == 409 and wbody.get("error"), (wcode, wbody))
        check("read while workbook is open still answers (cached state, no dropped connection)", rcode in (200, 409), rcode)
        check("server recovers once the workbook is released", state() and post("/api/project", {"name": "אחרי שחרור"})[0] == 200)
    check("no data lost after the locked attempt", len(state()["projects"]) >= base + 15 + 40)
    check("no stray lock or tmp files", not [f for f in os.listdir(TMP) if f.endswith((".lock", ".tmp"))], os.listdir(TMP))
finally:
    stop(srv)

fails = [r for r in results if not r[1]]
print("\n%d checks, %d passed, %d failed" % (len(results), len(results) - len(fails), len(fails)))
sys.exit(1 if fails else 0)
