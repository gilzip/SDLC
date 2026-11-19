"""Builds a fresh demo workbook: seed data, the five employees and the project role owners. Usage: prepare.py <out.xlsx>"""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "dashboard"))
import server

out = os.path.abspath(sys.argv[1])
if os.path.exists(out):
    os.remove(out)
server.DATA_PATH = out
d = server.load()
for name, role in [("דרור", "pm"), ("אייל", "readiness"), ("אדיר", "architect"), ("שמעון", "dev"), ("נחום", "qa")]:
    server.handle(d, "/api/employee", {"name": name, "email": "giltzip@gmail.com", "role": role})
owners = {"pm": "דרור", "readiness": "אייל", "architect": "אדיר", "dev": "שמעון", "qa": "נחום"}
for p in d["projects"]:
    server.handle(d, "/api/project/update", {"id": p["id"], "owners": owners})
server.save(d)
print("demo workbook ready:", out)
