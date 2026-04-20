# Session Handoff: Splitting a Heavy Batch Across Two Chats

Use this when a Claude task requires processing more binaries than fit in a single session's 32MB request budget (see `references/webflow-gotchas.md#8`), and you want to keep everything inside Claude Code — no API keys, no terminal scripts, no subagents.

The pattern: prep work happens in the original chat (no binaries touched). The heavy batch runs in a fresh chat the user opens manually. Both chats share state via filesystem files. When the worker is done, the original chat picks up for verification and push.

This pattern is not vision-specific. Any heavy Claude-generation batch (image classification, PDF summarization, transcription review) can use it.

## When to use this vs other patterns

| Situation | Use |
|---|---|
| Small batch (< 100 binaries) | Inline in one chat — `vision-pipeline.md` Pattern A |
| Medium batch (100–800), willing to wait while subagents block parent | Parallel subagents — `vision-pipeline.md` Pattern B |
| Large batch (> 800), OR you want to step away while it runs | **This pattern** |
| User explicitly says "all in Claude Code, no scripts, no subagents" | **This pattern** |
| User wants to use a different model for the worker (e.g., Sonnet for cheap mechanical work, Haiku for text-only) | **This pattern** |

Subagents block the parent during their run. Handoff frees the user — they can do other work while the worker chat grinds independently.

## Files

All handoff state lives in `.handoff/` at the project root:

```
.handoff/
├── task.md          ← the worker's self-contained brief (read-only for worker)
├── progress.md      ← shared status file. Both chats read; worker writes.
└── results.json     ← worker's output, consumed by original chat in steps 3–4
```

Add `.handoff/` to `.gitignore` — it's ephemeral, not source.

## Template: .handoff/task.md

The original chat generates this file from the task. The worker reads it and executes. Self-contained — the worker has no access to the original chat's history.

```markdown
# Worker Task: <task name>

## What to do

<one-paragraph description of the task in plain English>

## Inputs

- Task list: `batch/tasks.json` — array of <N> tasks, each with `{fileId, item_slug, binary_path, ...}`
- Binaries: `batch/binaries/<fileId>.jpg` (already prepped — AVIF→JPG, ≤2000px)

## For each task

1. Read the binary at `task.binary_path`
2. Generate the output per the prompt template below
3. Append `{fileId, output}` to `batch/results.json` IMMEDIATELY (resume-safe)
4. Append `fileId` to `batch/progress.txt`

## Prompt template

<paste the exact prompt the worker should use per item>

## Constraints

- <task-specific, e.g., alt text ≤125 chars, no "image of..." prefix>
- Update `.handoff/progress.md` STATUS field every 10 items (or every 5 minutes, whichever comes first)
- If you hit any failure (file missing, vision rejected), log to `.handoff/progress.md` NOTES and continue

## Resume safety

Before processing each task, check if its `fileId` is already in `batch/progress.txt`. If yes, skip — it was done by a prior worker run.

## When done

Set `.handoff/progress.md` STATUS to `COMPLETE`. Tell me in chat: "Done. <N>/<N> processed. Results in batch/results.json."
```

## Template: .handoff/progress.md

```markdown
# Worker Progress

STATUS: WAITING        # values: WAITING | IN_PROGRESS | COMPLETE | FAILED
DONE: 0 / 263
LAST_UPDATE: 2026-04-17 20:35
WORKER_MODEL: -

## Notes

(worker appends timestamped lines here for any failures or noteworthy events)
```

The worker updates STATUS to `IN_PROGRESS` when it starts, increments DONE periodically, and sets `COMPLETE` (or `FAILED` with a NOTES entry) at the end.

## The instruction the original chat prints to the user

Print this verbatim — clear steps, model recommendation, and the exact prompt to paste:

```
⚠️ This batch needs more context budget than a single chat can handle.
   <N> binaries × ~<KB> KB each = ~<MB> MB total.
   Anthropic's per-request cap is 32MB.

   Run it in a fresh Claude Code chat. Three steps:

   1. Open a new Claude Code chat IN THIS PROJECT FOLDER:
      → File menu → New Chat (Cmd+N), or run `claude` in the project terminal

   2. Select model: <recommended model — see below>

   3. Paste this prompt EXACTLY:

      ─────────────────────────────────────────────
      Read .handoff/task.md and execute the task.
      Update .handoff/progress.md STATUS and DONE
      counters every 10 items. Tell me in chat
      when STATUS is COMPLETE.
      ─────────────────────────────────────────────

   When the worker chat says it's done, come back to THIS chat
   and type `done`. I'll verify, generate the report, and run
   the push phase.
```

Substitute `<N>`, `<KB>`, `<MB>`, and `<recommended model>` based on the task.

## Model recommendation

The original chat picks the model for the worker based on task complexity:

| Task | Recommended model | Why |
|---|---|---|
| Vision-batch alt text (mechanical describe-what-you-see) | **Sonnet 4.6** | Vision-capable, fast, cheaper than Opus for mechanical work |
| Vision-batch with reasoning (categorization, brand-fit assessment) | **Opus 4.7** | Better judgment on nuanced calls |
| Text-only batch (summarization of pre-extracted PDF text) | **Haiku 4.5** | Cheapest, fast enough for short outputs |
| Mixed/uncertain | **Sonnet 4.6** | Reasonable default |

The user can always override. Print the recommendation, not a directive.

## After the worker finishes

When the user returns to the original chat and types `done`:

1. Read `.handoff/progress.md` — verify `STATUS: COMPLETE`. If it shows `IN_PROGRESS` or `FAILED`, ask the user (don't assume).
2. Read `batch/results.json` — verify item count matches expected.
3. Generate verification report (see `vision-pipeline.md` step 3).
4. Show the user, get explicit push approval.
5. Run the push phase (see `references/push-pattern.md`, plus `#patching-multi-image-fields` for image arrays).

If `progress.md` shows partial completion, the user has three options:
- **Resume:** open another fresh chat with the same prompt — worker will read `progress.txt` and skip done items.
- **Retry failed-only:** read NOTES in `progress.md`, write a new `task.md` scoped to just the failures.
- **Abandon:** delete `.handoff/` and start over.

## Resume safety

The worker's `batch/progress.txt` is the single source of truth for "what's done." If the worker chat crashes or the user closes the window mid-batch:

1. User opens another fresh chat
2. Pastes the same prompt
3. Worker reads `progress.txt`, sees `47 / 263` done, resumes from item 48

The progress file IS the resume mechanism. Per-item write-then-record (write result first, then append fileId to progress.txt) ensures no item is recorded as done unless its result was actually written.

## When NOT to use this pattern

- **The worker needs context from the original chat** (e.g., "use the same tone as the email we drafted earlier"). Handoff loses that context. Either include the relevant excerpt in `task.md`, or stay in the original chat.
- **Sub-100-item batches.** Inline is faster — no chat-switching overhead.
- **Time-sensitive jobs.** Handoff requires a human in the loop to open the worker chat. If the batch must run unattended, use a script with API key (outside this skill's scope).
