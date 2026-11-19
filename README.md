# SDLC flow desk

Manages the development flow of many projects, each with a subset of sub-modules. Every project x sub-module cell moves through four agent stages, and a human owner approves each stage before the next starts.

| # | Stage | Agent folder | Output (under `.ai/work/{project}/{sub-module}/`) |
|---|-------|--------------|-----------------------------------------------|
| 1 | Product | `Product/` | `requirement.md` |
| 2 | AI Dev | `AI-Dev/` | `ai-dev.md` |
| 3 | Dev | `Dev/` | `dev.md` |
| 4 | QA | `QA/` | `qa.md` (ends with PASS or FAIL) |

Each agent finishes its work, marks its stage ready (`POST /api/cell`, action `ready`), and stops. Approval is manual on the dashboard.

## Run

```
python -m pip install -r dashboard/requirements.txt
python dashboard/server.py [--port 8765] [--host 0.0.0.0]
```

All data lives in `dashboard/data.xlsx` (sheets: ראשי, פרויקטים, תת מודולים, שיוך, יומן). It is created on first run and never reset afterwards.
