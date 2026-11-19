"""Demo-only helper: shows the mails the flow desk wrote to its outbox as a small inbox, and a split-screen page
(dashboard | inbox | the recipient's browser) used for the recorded demo.

Usage: python mailbox.py --port 8801 --outbox <dir> --dash <dashboard port>
"""
import argparse, email, email.policy, email.utils, json, os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=8801)
ap.add_argument("--outbox", required=True)
ap.add_argument("--dash", type=int, default=8795)
A = ap.parse_args()


def load_mails():
    out = []
    if not os.path.isdir(A.outbox):
        return out
    for f in sorted(os.listdir(A.outbox)):
        with open(os.path.join(A.outbox, f), "rb") as fh:
            msg = email.message_from_binary_file(fh, policy=email.policy.default)
        name, addr = email.utils.parseaddr(str(msg["To"]))
        out.append({"id": f, "to": name, "addr": addr, "subject": str(msg["Subject"]),
                    "html": msg.get_body(("html",)).get_content()})
    return out


WRAPPER = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><title>הדגמה</title>
<style>
html,body{margin:0;height:100%;background:#dfe6ee;font-family:Segoe UI,Arial,sans-serif}
.app{display:grid;grid-template-columns:1020px 1fr;gap:10px;padding:10px;height:calc(100% - 130px);box-sizing:border-box}
.pane{background:#fff;border:1px solid #b9c5d1;border-radius:10px;overflow:hidden;display:flex;flex-direction:column;min-height:0}
.pane h3{margin:0;padding:6px 12px;font-size:14px;background:#14202b;color:#fff;font-weight:600}
.pane iframe{border:0;flex:1;width:100%;min-height:0}
.right{display:grid;grid-template-rows:1fr 1fr;gap:10px;min-height:0}
</style>
<div class="app">
  <div class="pane"><h3>הדשבורד (המסך הראשי)</h3><iframe name="dash" src="http://localhost:__DASH__/"></iframe></div>
  <div class="right">
    <div class="pane"><h3>תיבת הדואר של בעלי התפקידים (הדמיה)</h3><iframe name="mailbox" src="/mailbox"></iframe></div>
    <div class="pane"><h3>הדפדפן של בעל התפקיד: דף האישור שנפתח מהקישור</h3><iframe name="apv" src="/idle"></iframe></div>
  </div>
</div></html>"""

MAILBOX = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8">
<style>
body{margin:0;font-family:Segoe UI,Arial,sans-serif;font-size:13px;color:#14202b;background:#fff}
#list{max-height:132px;overflow:auto;border-bottom:1px solid #d6dee6}
.item{padding:5px 12px;border-bottom:1px solid #eef2f6;cursor:pointer;display:flex;gap:8px;align-items:baseline}
.item.sel{background:#e6edfc}.item .to{font-weight:700;min-width:62px}.item .sub{color:#34495e;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
#hdr{padding:6px 12px;background:#f3f6f9;color:#5a6978;font-size:12px}
#mail{padding:8px 14px;overflow:auto}
.cnt{float:left;background:#2556d9;color:#fff;border-radius:10px;padding:0 8px;font-size:12px}
</style><div id="hdr">נכנסו <span class="cnt" id="cnt">0</span></div><div id="list"></div><div id="mail"></div>
<script>
let mails = [], sel = null;
function render() {
  document.getElementById('cnt').textContent = mails.length;
  const last = mails.slice(-6).reverse();
  document.getElementById('list').innerHTML = last.map(m => `<div class="item ${m.id===sel?'sel':''}" data-id="${m.id}"><span class="to">${m.to}</span><span class="sub">${m.subject.replace('[Flow] ','')}</span></div>`).join('');
  const m = mails.find(x => x.id === sel) || mails.at(-1);
  if (m) {
    document.getElementById('mail').innerHTML = '<div style="color:#5a6978;margin-bottom:6px">אל: <b>' + m.to + '</b> &lt;' + m.addr + '&gt;<br>נושא: ' + m.subject + '</div>' + m.html;
    document.querySelectorAll('#mail a').forEach(a => a.target = 'apv');
  }
}
async function poll() { try { const n = await (await fetch('/mails.json')).json(); if (n.length !== mails.length) { mails = n; render(); } } catch (e) {} }
// the recording script picks which mail is on screen
window.__show = (needle) => { const m = [...mails].reverse().find(x => x.subject.includes(needle)); if (!m) return false; sel = m.id; render(); return true; };
document.addEventListener('click', e => { const it = e.target.closest('.item'); if (it) { sel = it.dataset.id; render(); } });
setInterval(poll, 500); poll();
</script></html>"""

IDLE = """<!doctype html><html lang="he" dir="rtl"><meta charset="utf-8"><body style="font-family:Segoe UI,Arial;background:#f3f6f9;color:#5a6978;display:grid;place-items:center;height:100vh;margin:0">
<div>הקישור מהמייל ייפתח כאן</div></body></html>"""


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, body, ctype="text/html; charset=utf-8"):
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        p = self.path.split("?")[0]
        if p == "/wrapper":
            self.send(WRAPPER.replace("__DASH__", str(A.dash)))
        elif p == "/mailbox":
            self.send(MAILBOX)
        elif p == "/mails.json":
            self.send(json.dumps(load_mails(), ensure_ascii=False), "application/json; charset=utf-8")
        elif p == "/idle":
            self.send(IDLE)
        else:
            self.send("not found")


ThreadingHTTPServer(("127.0.0.1", A.port), H).serve_forever()
