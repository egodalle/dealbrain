---
description: Run one backlog story through Product Owner → Architect → Data Engineer → Architect review → Tester → Product Owner acceptance
argument-hint: DB-NN
---

Run story **$ARGUMENTS** through the team flow in CLAUDE.md. Use the Agent tool with each subagent in turn. Wait for each step to finish and check that its file exists before you start the next step.

1. **product-owner**: "Prepare story $ARGUMENTS: write or refresh docs/work/$ARGUMENTS/story.md from the template, with testable acceptance criteria. Set it to ready or list what blocks it."
   Stop and report to the human if it isn't `ready`.
2. **architect**: "Design $ARGUMENTS: write docs/work/$ARGUMENTS/design.md, plus an ADR if needed."
3. **data-engineer**: "Implement $ARGUMENTS on branch feat/$ARGUMENTS-*, following design.md. Write impl-notes.md and set the status to review."
4. **architect**: "Review the $ARGUMENTS diff against design.md and CLAUDE.md. Write review.md."
   If there are blocking findings, send review.md back to the data-engineer and repeat steps 3–4. Allow at most 2 loops.
5. **tester**: "Verify $ARGUMENTS independently from a clean state. Run every acceptance criterion for real on this Mac (Docker, live database, network, test-account credentials in .env). SKIPPED counts as FAIL; use BLOCKED only for something that truly doesn't exist yet. Write test-report.md."
   If any criterion fails, send the report back to the data-engineer, then repeat steps 4–5. Allow at most 2 loops.
6. **product-owner**: "Accept or return $ARGUMENTS based on test-report.md. Any SKIPPED or BLOCKED criterion means it is not done: return it or set `blocked: <reason>`. Update docs/backlog.md."

Finish by telling the human: the story status, the acceptance criteria passed, the eval numbers, the branch name, and whether the branch is ready for a PR. Never tell a subagent to skip live checks. Do not merge or push without the human's go-ahead.
