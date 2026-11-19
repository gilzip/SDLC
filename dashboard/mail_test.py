"""Tests the hand-over e-mails and the approve links. Own server, own temp workbook, mails go to a temp outbox
and to a local fake SMTP server. Nothing is ever sent to a real address.

Run:  python dashboard/mail_test.py
"""
import email, email.policy, json, os, re, socket, subprocess, sys, tempfile, threading, time, urllib.parse, urllib.request as u
from urllib.error import HTTPError

HERE = os.path.dirname(os.path.abspath(__file__))
PORT, SMTP_PORT = 8792, 8793
B = "http://localhost:%d" % PORT
TMP = tempfile.mkdtemp(prefix="flowmail_")
XLSX = os.path.join(TMP, "m.xlsx")
OUTBOX = os.path.join(TMP, "outbox")
results = []


def check(name, cond, detail=""):
    results.append(bool(cond))
    print(("PASS " if cond else "FAIL ") + name + ((" :: " + str(detail)) if detail and not cond else ""), flush=True)


def post(path, body):
    try:
        return u.urlopen(u.Request(B + path, json.dumps(body).encode(), {"Content-Type": "application/json"})).status
    except HTTPError as e:
        return e.code


def raw(url, data=None):
    try:
        r = u.urlopen(u.Request(url, data, {"Content-Type": "application/x-www-form-urlencoded"} if data else {}))
        return r.status, r.read().decode("utf-8")
    except HTTPError as e:
        return e.code, e.read().decode("utf-8")


state = lambda: json.load(u.urlopen(B + "/api/state"))


def mails():
    if not os.path.isdir(OUTBOX):
        return []
    out = []
    for f in sorted(os.listdir(OUTBOX)):
        with open(os.path.join(OUTBOX, f), "rb") as fh:
            out.append(email.message_from_binary_file(fh, policy=email.policy.default))
    return out


def wait_mails(n, timeout=8):
    end = time.time() + timeout
    while time.time() < end:
        if len(mails()) >= n:
            return mails()
        time.sleep(0.1)
    return mails()


def link_of(msg):
    return re.search(r"(http://\S+/approve\?t=\S+)", msg.get_body(("plain",)).get_content()).group(1)


# ---------------------------------------------------------------- a minimal SMTP receiver
received = []


def smtp_server(sock):
    while True:
        try:
            conn, _ = sock.accept()
        except OSError:
            return
        f = conn.makefile("rwb")

        def say(line):
            f.write((line + "\r\n").encode()); f.flush()

        say("220 test ESMTP")
        data, in_data, rcpt, sender = [], False, [], ""
        while True:
            line = f.readline()
            if not line:
                break
            text = line.decode("utf-8", "replace").rstrip("\r\n")
            if in_data:
                if text == ".":
                    received.append({"from": sender, "to": rcpt, "data": "\n".join(data)})
                    say("250 queued"); in_data = False
                else:
                    data.append(text[1:] if text.startswith("..") else text)
                continue
            cmd = text.upper()
            if cmd.startswith(("EHLO", "HELO")):
                say("250 test")
            elif cmd.startswith("MAIL FROM"):
                sender = text.split(":", 1)[1]; say("250 ok")
            elif cmd.startswith("RCPT TO"):
                rcpt.append(text.split(":", 1)[1]); say("250 ok")
            elif cmd == "DATA":
                say("354 go"); in_data = True
            elif cmd == "QUIT":
                say("221 bye"); break
            else:
                say("250 ok")
        conn.close()


lsock = socket.socket(); lsock.bind(("127.0.0.1", SMTP_PORT)); lsock.listen(5)
threading.Thread(target=smtp_server, args=(lsock,), daemon=True).start()

srv = subprocess.Popen([sys.executable, os.path.join(HERE, "server.py"), "--port", str(PORT), "--data", XLSX],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
try:
    for _ in range(60):
        try:
            state(); break
        except Exception:
            time.sleep(0.2)

    # ---- people: each role has its own mailbox in this test
    for n, r in [("דרור", "pm"), ("אייל", "readiness"), ("אדיר", "architect"), ("שמעון", "dev"), ("נחום", "qa")]:
        post("/api/employee", {"name": n, "email": "%s@example.test" % {"דרור": "dror", "אייל": "eyal", "אדיר": "adir", "שמעון": "shimon", "נחום": "nahum"}[n], "role": r})
    s = state()
    proj = {p["name"]: p for p in s["projects"]}["ממשק לרובוט"]
    mod = proj["modules"][0]
    post("/api/project/update", {"id": proj["id"], "owners": {"pm": "דרור", "readiness": "אייל", "architect": "אדיר", "dev": "שמעון", "qa": "נחום"}})
    cellkey = proj["id"] + ":" + mod
    stages = lambda: "".join(x[0] for x in state()["cells"][cellkey]["stages"])
    check("changing owners sends no mail", len(mails()) == 0)

    # ---- start -> mail to the first owner
    post("/api/cell", {"project": proj["id"], "module": mod, "action": "start", "who": "גיל"})
    ms = wait_mails(1)
    check("starting the Flow mails the first stage owner", len(ms) == 1 and "dror@example.test" in ms[0]["To"], [m["To"] for m in ms])
    m0 = ms[0]
    check("subject names project, sub-module and stage", all(x in m0["Subject"] for x in ["ממשק לרובוט", "מנהל מוצר"]), m0["Subject"])
    link = link_of(m0)
    html_part = m0.get_body(("html",)).get_content()
    check("html mail has an approve button with the same link", "approve?t=" in html_part and "אשר: סיום שלב מנהל מוצר" in html_part)

    # ---- opening the link must not change anything, approving through the form does
    code, page = raw(link)
    check("link opens a confirmation page, no change yet", code == 200 and "אשר: סיום שלב מנהל מוצר" in page and stages() == "rppppp", (code, stages()))
    tok = urllib.parse.parse_qs(urllib.parse.urlsplit(link).query)["t"][0]
    code, page = raw(B + "/approve", urllib.parse.urlencode({"t": tok}).encode())
    check("approving through the link updates the system", code == 200 and "האישור נקלט" in page and stages() == "drpppp", (code, stages()))
    log = state()["cells"][cellkey]["log"]
    check("log says it was approved through the mail by the owner", any("דרור (דרך המייל)" in l["m"] for l in log))
    ms = wait_mails(2)
    check("approval mails the next owner automatically", len(ms) == 2 and "eyal@example.test" in ms[1]["To"], [m["To"] for m in ms])
    check("body tells who finished the previous stage", "מנהל מוצר" in ms[1].get_body(("plain",)).get_content())

    # ---- replay, tampering
    code, page = raw(B + "/approve", urllib.parse.urlencode({"t": tok}).encode())
    check("using the same link again changes nothing", code == 200 and "כבר אושר" in page and stages() == "drpppp", stages())
    time.sleep(0.5)
    check("replay sends no extra mail", len(mails()) == 2)
    check("tampered link is rejected", raw(B + "/approve?t=" + tok[:-3] + "abc")[0] == 400)
    check("garbage link is rejected", raw(B + "/approve?t=garbage")[0] == 400)
    check("link to a stage that is not current does nothing",
          "עדיין לא הגיע" in raw(B + "/approve?t=" + urllib.parse.quote(subprocess.run([sys.executable, "-c",
              "import sys; sys.path.insert(0, r'%s'); import server; server.DATA_PATH = r'%s'; print(server.make_token('S', '%s', '%s', 4))" % (HERE, XLSX, proj["id"], mod)],
              capture_output=True, text=True).stdout.strip()))[1])

    # ---- go back: the previous owner is mailed with the note
    link1 = link_of(ms[1])
    raw(B + "/approve", urllib.parse.urlencode({"t": urllib.parse.parse_qs(urllib.parse.urlsplit(link1).query)["t"][0]}).encode())
    check("second approval through its own link", stages() == "ddrppp", stages())
    ms = wait_mails(3)
    check("third owner (architect) mailed", "adir@example.test" in ms[2]["To"], [m["To"] for m in ms])
    post("/api/cell", {"project": proj["id"], "module": mod, "action": "complete", "stage": 2, "who": "x"})
    post("/api/cell", {"project": proj["id"], "module": mod, "action": "back", "stage": 3, "who": "שמעון", "note": "חסרה ולידציה"})
    ms = wait_mails(5)
    back = ms[-1]
    check("sending back mails the previous owner with the note", "adir@example.test" in back["To"] and "חסרה ולידציה" in back.get_body(("plain",)).get_content(), [m["To"] for m in ms])

    # ---- unassigned stage: no mail, and the log says why
    post("/api/cell/assign", {"project": proj["id"], "module": mod, "stage": 3, "employee": ""})
    before = len(mails())
    post("/api/cell", {"project": proj["id"], "module": mod, "action": "complete", "stage": 2, "who": "x"})
    time.sleep(1.2)
    check("no owner for the next stage: no mail", len(mails()) == before)
    check("the log explains why no mail went out", any("אין אחראי לשלב" in l["m"] for l in state()["cells"][cellkey]["log"]))
    post("/api/cell/assign", {"project": proj["id"], "module": mod, "stage": 3, "employee": "שמעון"})

    # ---- finish the sub-module: the QA owner gets the project-level mail and can approve it by link
    n0 = len(mails())
    for k in (3, 4, 5):
        post("/api/cell", {"project": proj["id"], "module": mod, "action": "complete", "stage": k, "who": "x"})
    ms = wait_mails(n0 + 3)
    last = ms[-1]
    check("when the last sub-module finishes, QA is mailed about the project check",
          "nahum@example.test" in last["To"] and "בדיקה קצה לקצה לפרויקט" in last["Subject"], (last["To"], last["Subject"]))
    ptok = urllib.parse.parse_qs(urllib.parse.urlsplit(link_of(last)).query)["t"][0]
    code, page = raw(B + "/approve?t=" + urllib.parse.quote(ptok))
    check("project link shows the approval page", code == 200 and "הפרויקט נבדק ותקין קצה לקצה" in page)
    raw(B + "/approve", urllib.parse.urlencode({"t": ptok}).encode())
    pj = [p for p in state()["projects"] if p["id"] == proj["id"]][0]
    check("approving the project through the link marks it approved for production", pj["e2e"] == "done" and "נחום" in pj["e2e_by"], pj["e2e"])

    # ---- real SMTP path (to the local fake server)
    with open(os.path.join(TMP, "mail.json"), "w", encoding="utf-8") as f:
        json.dump({"host": "127.0.0.1", "port": SMTP_PORT, "security": "none", "from": "flow@example.test", "base_url": "http://flow.example.test:9999"}, f)
    other = {p["name"]: p for p in state()["projects"]}["צה\"ל"]
    post("/api/project/update", {"id": other["id"], "owners": {"pm": "דרור", "readiness": "אייל"}})
    post("/api/cell", {"project": other["id"], "module": other["modules"][0], "action": "start", "who": "גיל"})
    for _ in range(60):
        if received:
            break
        time.sleep(0.1)
    check("SMTP configured: the mail goes out over SMTP", len(received) == 1 and "dror@example.test" in received[0]["to"][0], received)
    msg = email.message_from_string(received[0]["data"], policy=email.policy.default) if received else None
    check("SMTP mail uses the configured sender and public base url",
          msg is not None and "flow@example.test" in msg["From"] and "http://flow.example.test:9999/approve?t=" in msg.get_body(("plain",)).get_content())
    time.sleep(0.5)
    check("log records that the mail was sent", any("נשלח מייל לדרור" in l["m"] for l in state()["cells"][other["id"] + ":" + other["modules"][0]]["log"]))

    # ---- a broken SMTP server must not break the Flow
    with open(os.path.join(TMP, "mail.json"), "w", encoding="utf-8") as f:
        json.dump({"host": "127.0.0.1", "port": 1, "security": "none"}, f)
    check("SMTP down: the Flow action still succeeds",
          post("/api/cell", {"project": other["id"], "module": other["modules"][0], "action": "complete", "stage": 0, "who": "דרור"}) == 200)
    failed = False
    for _ in range(100):  # a refused connection takes a couple of seconds on Windows
        failed = any("נכשלה" in l["m"] for l in state()["cells"][other["id"] + ":" + other["modules"][0]]["log"])
        if failed:
            break
        time.sleep(0.2)
    check("SMTP down: the failure is logged on the task", failed)
    gi = open(os.path.join(HERE, "..", ".gitignore"), encoding="utf-8").read()
    check("secret key, mail settings and outbox are git-ignored", all(x in gi for x in ["dashboard/mail.json", "dashboard/.flow-secret", "dashboard/outbox/"]), gi)
finally:
    srv.terminate(); srv.wait(); lsock.close()

print("\n%d checks, %d passed, %d failed" % (len(results), sum(results), len(results) - sum(results)))
sys.exit(0 if all(results) else 1)
