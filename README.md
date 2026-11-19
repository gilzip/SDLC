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

Colors: each stage has its own color, so one look at the main screen shows where every sub-module is. A cell takes the color of the stage it is in; grey = not started, green = finished.

| Stage | Color |
|-------|-------|
| Product | blue |
| Code Readiness | violet |
| AI Dev | orange |
| Dev | yellow |
| QA | pink |
| End-to-end check | teal |

The same colors fill the cells of the `ראשי` sheet in the workbook, which also has a legend. The colors are defined once, in `STAGES` in `dashboard/server.py`.

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

## E-mail hand-over with an approve link

When a stage hands over to the next owner, that owner gets an e-mail with a button. The button opens a confirmation page, and pressing "אשר" there closes the stage and updates the system automatically; the task then moves on and the next owner is mailed in turn. Mails go out when:

- the Flow starts (first owner),
- a stage is approved (next owner, with who finished the previous one),
- a task is sent back or reopened (the owner it returns to, with the note),
- the last sub-module of a project finishes (the QA owner, to approve the project-level end-to-end check and release to production).

Opening the link changes nothing; only the button on the page does. Links are signed (HMAC, key in `dashboard/.flow-secret`, created on first use), cannot be forged, and do nothing once the stage is no longer waiting. The approval is logged under the owner's name with "(דרך המייל)". If a stage has no owner or the owner has no address, no mail is sent and the task log says so. A failed send never blocks the Flow; it is logged on the task.

**Setup.** Copy `dashboard/mail.example.json` to `dashboard/mail.json` and fill in your SMTP server, or use the environment variables `FLOW_SMTP_HOST`, `FLOW_SMTP_PORT`, `FLOW_SMTP_USER`, `FLOW_SMTP_PASSWORD`, `FLOW_SMTP_FROM`, `FLOW_SMTP_SECURITY` (`starttls`, `ssl` or `none`) and `FLOW_BASE_URL`. Keep the password in `FLOW_SMTP_PASSWORD`, not in the file. `base_url` is the address the recipients can reach the dashboard on (for example `http://my-pc:8765`, with the server started with `--host 0.0.0.0`); the default `http://localhost:8765` only works on the machine running the server.

Until SMTP is configured nothing is sent: each mail is written as an `.eml` file to `dashboard/outbox/` so you can see exactly what would go out.

Tests: `python dashboard/e2e_test.py` (flow, Excel, concurrency) and `python dashboard/mail_test.py` (mails and links, with a local fake SMTP server).

## Run

```
python -m pip install -r dashboard/requirements.txt
python dashboard/server.py [--port 8765] [--host 0.0.0.0]
```

All data lives in `dashboard/data.xlsx` (sheets: ראשי, פרויקטים, תת מודולים, שיוך, יומן). It is created on first run and never reset afterwards. Files written by the earlier four-stage version are read and upgraded.
