---
name: project-bootstrap
description: Use when starting a task before exploring, answering, or editing if repository instructions (AGENTS.md or equivalent) are not already loaded in context—such as when working directory differs from repo root, in multi-workspace sessions, or in harnesses that do not auto-inject root docs.
---

# Project Bootstrap

Load repository instructions before reading source files, answering project questions, or editing code whenever those instructions are not already in your context.

## When to Skip

Skip if the target repository's `AGENTS.md` (or equivalent root instructions) is already loaded in your initial context.

## Steps

1. **Resolve the target repository root(s)**: Never assume initial `cwd` is the repo root—sessions often start in a subdirectory, git worktree, symlinked path, temp/attachment folder, or multi-workspace root. Resolve the target root from workspace metadata, by walking up from target file paths to `.git` or `AGENTS.md`, or via `git rev-parse --show-toplevel`.
2. **Read root instruction files**: Read `<repo-root>/AGENTS.md` directly. If absent or delegated, check `CLAUDE.md`, `GEMINI.md`, `.agents/AGENTS.md`, `.agents/GEMINI.md`, or `.agents/rules/*.md`. Also check any directory-level `AGENTS.md` along the path to files you touch.
3. **Follow entrypoints and completion hooks**: Read any knowledge-base index, architecture doc, or workflow doc required by `AGENTS.md` before designing or proposing changes, and execute any verification or post-change sync steps it mandates before finishing.

## Red Flags — STOP and Load First

| Rationalization | Reality |
|---|---|
| "Short on time / user pointed to one file" | Reading `AGENTS.md` takes one call and prevents violating mandatory repo rules. |
| "Initial `cwd` has no `AGENTS.md`" | `cwd` often differs from the repo root; resolve the root from target paths or workspace roots. |
| "`ls` failed or directory listing is restricted" | Read `<repo-root>/AGENTS.md` directly by path instead of skipping it. |
| "I'll read code first, docs later" | Root docs specify which architecture docs, helpers, and verification commands are mandatory. |
