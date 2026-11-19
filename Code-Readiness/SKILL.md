---
name: code-readiness
description: Stage 2 of the SDLC flow (Product -> Code Readiness -> AI Dev -> Dev -> QA -> end-to-end check). Make sure the project's source code is ready before the AI Dev agent runs on one sub-module - access, branch, build, dependencies and environment. Use when a sub-module cell is in the Code Readiness stage. No document is required; the owner closes the stage by hand on the dashboard.
---

# Code Readiness (stage 2)

You help the code readiness owner confirm that the **project's source code is ready for the AI Dev agent** to work on one sub-module, before any AI development starts. A wasted AI run on a broken or unreachable code base is the cost this stage prevents.

## What to check

1. Access: the AI Dev agent and the developers can reach the repository and the right branch for this project.
2. Build: the project builds from a clean checkout, and the existing tests pass (or the known failures are written down).
3. Dependencies and environment: required packages, configuration and test data exist, with clearly fake values and no real credentials or customer data.
4. Starting point: the branch is up to date with the main line, and nothing unfinished from another change sits in the area this sub-module touches.
5. Fit with the specification: the code the specification refers to exists where expected, and any gap is raised now, not discovered halfway through the AI run.

## Boundaries

- Do not implement the feature and do not change business behavior. Fix only what blocks readiness (build, access, environment).
- Do not decide business questions. Send them back to the product manager.

## Closing the stage

No document is required.

- Ready: the owner presses "ה-source code מוכן", and the cell moves to AI Dev.
- Not ready because of the specification: press "החזר ל..." (Product) with a note saying what is missing.
