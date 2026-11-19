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
2. **Parallelize root instruction reads**: On the very first turn (including in parallel with loading this skill when the repo root is known), read `<repo-root>/AGENTS.md` directly. If absent or delegated, batch reads of `CLAUDE.md`, `GEMINI.md`, `.agents/AGENTS.md`, `.agents/GEMINI.md`, `.agents/rules/*.md`, and any directory-level `AGENTS.md` along the path to files you touch.
3. **Batch mandatory entrypoints; load `MEMORY.md` only on demand**: Read only the startup-required entrypoints specified by `AGENTS.md` (such as a knowledge-base index or architecture doc) in parallel before designing or proposing changes. Read `MEMORY.md` (or long-term memory notes) **only on demand** when the task needs historical context or debugging memory—not as a mandatory startup read. Execute any verification or post-change sync steps mandated by `AGENTS.md` before finishing.

## Red Flags — STOP and Load First

| Rationalization | Reality |
|---|---|
| "Short on time / user pointed to one file" | Reading `AGENTS.md` takes one parallel call and prevents violating mandatory repo rules. |
| "Initial `cwd` has no `AGENTS.md`" | `cwd` often differs from the repo root; resolve the root from target paths or workspace roots. |
| "`ls` failed or directory listing is restricted" | Read `<repo-root>/AGENTS.md` directly by path instead of skipping it. |
| "I'll read code first, docs later" | Root docs specify which architecture docs, helpers, and verification commands are mandatory. |
