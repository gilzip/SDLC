# SDLC flow desk

Manages the development flow of many projects, each with a subset of sub-modules. Every project x sub-module cell moves through five stages. Each stage is closed by hand by its owner on the dashboard, and only then does the cell move on. No stage has to produce a document.

| # | Stage | Agent folder | Closed by pressing |
|---|-------|--------------|--------------------|
| 1 | Product | `Product/` | סיים איפיון |
| 2 | AI Dev (runs outside the system) | `AI-Dev/` | פיתוח ה-AI הסתיים |
| 3 | Dev | `Dev/` | הקוד נבדק ותקין |
| 4 | QA | `QA/` | QA אישר |
| 5 | End-to-end check | `QA/` | המודול נבדק ותקין קצה לקצה |

A stage owner who finds a problem presses "return to the previous stage" with a note. A cell turns green only after stage 5.

Colors: red = not started, light blue = in progress, green = done.

## Run

```
python -m pip install -r dashboard/requirements.txt
python dashboard/server.py [--port 8765] [--host 0.0.0.0]
```

All data lives in `dashboard/data.xlsx` (sheets: ראשי, פרויקטים, תת מודולים, שיוך, יומן). It is created on first run and never reset afterwards. Files written by the earlier four-stage version are read and upgraded.
