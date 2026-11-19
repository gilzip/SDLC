# SDLC flow desk

Manages the development flow of many projects, each with a subset of sub-modules. Every project x sub-module cell moves through six stages. Each stage is closed by hand by its owner on the dashboard, and only then does the cell move on. No stage has to produce a document.

| # | Stage | Agent folder | Closed by pressing |
|---|-------|--------------|--------------------|
| 1 | Product | `Product/` | סיים איפיון |
| 2 | Code Readiness | `Code-Readiness/` | ה-source code מוכן |
| 3 | AI Dev (runs outside the system) | `AI-Dev/` | פיתוח ה-AI הסתיים |
| 4 | Dev | `Dev/` | הקוד נבדק ותקין |
| 5 | QA | `QA/` | QA אישר |
| 6 | End-to-end check | `QA/` | המודול נבדק ותקין קצה לקצה |

**Project-level end-to-end check.** Each project row also has a last column. It opens only when every sub-module of the project has finished all six stages. The owner then approves by hand that the whole project works end to end. If a problem is found, the owner reopens the relevant sub-module at a chosen stage with a note, which voids the approval until that sub-module is done again. Adding a new unfinished sub-module to the project voids it too.

A stage owner who finds a problem presses "return to the previous stage" with a note. A cell turns green only after stage 6.

Colors: red = not started, light blue = in progress, green = done.

## Employees and task owners

Every stage of every cell is assigned to an employee. Employees live in the `עובדים` sheet (name, email, role) and are managed from the "עובדים" button. Employees are identified by name, so several employees can share one email.

| Role | Responsible for |
|------|-----------------|
| מנהל מוצר (product manager) | stage 1, the specification |
| אחראי מוכנות קוד (code readiness owner) | stage 2, confirming the source code is ready before the AI Dev agent runs |
| ארכיטקט (architect) | stage 3, running the AI Dev agent outside the system |
| מתכנת (programmer) | stage 4, checking the generated code works against the requirements |
| QA | stages 5 and 6, and the project-level end-to-end check |

Set the five role owners per project in the project dialog; they apply to every task of that project. Any single task can then be reassigned in the cell dialog. The header filter shows only the tasks currently waiting on a chosen employee. Emails are stored, but the system does not send any messages.

## Run

```
python -m pip install -r dashboard/requirements.txt
python dashboard/server.py [--port 8765] [--host 0.0.0.0]
```

All data lives in `dashboard/data.xlsx` (sheets: ראשי, פרויקטים, תת מודולים, שיוך, יומן). It is created on first run and never reset afterwards. Files written by the earlier four-stage version are read and upgraded.
