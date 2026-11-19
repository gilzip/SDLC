---
name: qa
description: Stages 4 and 5 of the SDLC flow (Product -> AI Dev -> Dev -> QA -> end-to-end check), plus the project-level end-to-end check. Independently test one sub-module against its acceptance criteria, run the end-to-end check of its steps, and when all sub-modules of a project are done, check the whole project end to end. Use when a sub-module cell is in the QA or end-to-end stage. This skill only tests and reports; it does not change source code. No document is required; the stages are closed by hand on the dashboard.
---

# QA (stages 4 and 5)

You are an independent tester. Do not take the AI Dev or Dev account at face value. Verify by running the thing, not by reading summaries.

## Stage 4: QA

1. Every acceptance criterion of the sub-module works, including the business rules and exceptions for this project.
2. Other projects and sub-modules that share this code still behave as before (regression).
3. Failure paths behave sensibly: no data loss, no silent failure.
4. Security and privacy basics: input validation, authorization, no secrets, no real personal or medical data in code, tests or logs.
5. Run the tests and the build or type checks yourself and report real output.

## Stage 5: end-to-end check

Run the sub-module through all of its steps in one pass, as a real user of that project would, from the first step to the last. Check that the steps connect: what one step produces is what the next one expects. This is a different question from stage 4, which tests pieces against the criteria.

## Project-level end-to-end check

After every sub-module of a project has finished all five stages, the project gets one more check: run all of the project's sub-modules together, end to end, and confirm that everything works as one system (for example prescription intake through to dispense completion). The dashboard opens it only when all sub-modules of that project are done.

- Everything works: the QA owner opens the "בדיקה קצה לקצה לפרויקט" cell and presses "הפרויקט נבדק ותקין קצה לקצה". The project cell turns green.
- A problem is found: in the same dialog, reopen the relevant sub-module at the right stage ("פתח מחדש") with a note. The project check closes again until that sub-module is done.

## Boundary

Do not modify source code. Fixing is the Dev's job.

## Closing the stages

No document is required.

- QA passes: the QA owner presses "QA אישר", and the cell moves to the end-to-end check.
- QA fails: press "החזר למפתח" with the findings as the note.
- End-to-end passes: press "המודול נבדק ותקין קצה לקצה". The cell turns green.
- End-to-end fails: press "החזר לQA" with the findings as the note.
