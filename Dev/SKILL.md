---
name: dev
description: Stage 4 of the SDLC flow (Product -> Code Readiness -> AI Dev -> Dev -> QA -> end-to-end check). The developer checks that the code the AI created for one project and sub-module works and is sound, fixing what is not. Use when a sub-module cell is in the Dev stage. No document is required; the developer closes the stage by hand on the dashboard.
---

# Dev (stage 4)

You help the developer verify and fix the code the AI created for one **project x sub-module** cell.

## What to check

1. Run it and the tests. Does it actually do what the specification and its acceptance criteria say?
2. Review the real `git diff` against the specification. Fix what is wrong or missing.
3. Look past the happy path: error handling, edge cases, input validation, authorization, secrets, personal and medical data, performance, concurrency.
4. Confirm it fits project conventions and does not change behavior of other projects or sub-modules that share the code.
5. Keep the diff focused. Remove anything unrelated.

## Boundaries

- Fix what is wrong, risky or against conventions. Do not rewrite for taste, and do not widen the scope.
- No real credentials or real customer data in code, tests or docs.
- Business questions go back to the product manager, not decided here.

## Closing the stage

No document is required.

- Code works and is sound: the developer presses "הקוד נבדק ותקין", and the cell moves to QA.
- Not good enough to fix here: the developer presses "החזר לפיתוח AI" with a note saying what is wrong, and the cell returns to AI Dev.
