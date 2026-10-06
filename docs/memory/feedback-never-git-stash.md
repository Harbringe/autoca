---
name: feedback-never-git-stash
description: "Never run git stash (or any command that sets aside uncommitted work) in this repo, not even as a \"check\" in a chained command; it happened twice and risks losing work."
metadata:
  node_type: memory
  type: feedback
---

Do not run `git stash` / `git stash pop` / `git checkout -- .` style commands, even inside a longer chained shell line meant for something else (for example "check the tests alone, then stash to compare"). Twice now a stash slipped into a command and set aside a large amount of uncommitted work; it was restored with `git stash pop` both times, but only because it was noticed immediately.

**Why:** the working tree usually holds many uncommitted files at once (migrations, tests, generated schema, routeTree.gen.ts), some untracked, and a stash only covers tracked ones, so a mistake can strand or mangle work. The user has not asked for it either time.

**How to apply:** to compare against the last commit, use `git diff`, `git show HEAD:path`, or a throwaway `git worktree`, never a stash. If a test fails only under the full suite, re-run that file alone (flaky jsdom timeouts under load are real here: `src/routes/-routes.test.tsx` times out at 5s when the whole web suite runs in parallel but passes alone). Commit early at green checkpoints so the tree is small.
