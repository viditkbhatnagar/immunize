# How to use these docs with Claude Code plan mode

Four documents in this folder:

| File | Purpose |
|---|---|
| `PLAN.md` | Master build plan with phased milestones |
| `ARCHITECTURE.md` | System design, data flow, competitive landscape |
| `SPEC.md` | Precise specifications for every component |
| `PYPI_PUBLISHING.md` | How to ship it to the world |

## Recommended workflow

### Step 0: One-time setup (15 min)

```bash
# Create the empty repo
mkdir ~/code/immunize
cd ~/code/immunize
git init
gh repo create viditkbhatnagar/immunize --public --source=. --remote=origin

# Copy the four plan docs into a subfolder
mkdir _planning
cp /path/to/PLAN.md /path/to/ARCHITECTURE.md /path/to/SPEC.md /path/to/PYPI_PUBLISHING.md _planning/

# Commit the plan
git add _planning
git commit -m "Add planning docs"
git push -u origin main
```

### Step 1: Open Claude Code in plan mode

```bash
cd ~/code/immunize
claude --plan
```

(Or in interactive mode, press Shift+Tab twice to enter plan mode.)

### Step 2: First prompt — bootstrap

Paste this verbatim:

> Read `_planning/PLAN.md`, `_planning/ARCHITECTURE.md`, and `_planning/SPEC.md` in full before doing anything else. These documents are authoritative — do not re-architect or re-scope without flagging it explicitly.
>
> After reading, propose a plan for **Phase 0 only** (repo setup from PLAN.md). Do not code yet. Wait for my approval.
>
> Important constraints:
> - Use hatchling, not setuptools.
> - Use Typer, not argparse.
> - Use the Anthropic SDK directly, not LangChain.
> - Do not skip the pytest verification harness — it is the core product differentiator.

### Step 3: Review the plan, push back

When Claude Code proposes its Phase 0 plan, check it against PLAN.md Phase 0. If it invents new steps or skips ones, correct it. Approve only when it matches.

### Step 4: Execute Phase 0, then loop for Phases 1–4

After each phase completes:

1. Review the code it wrote.
2. Run the tests.
3. Manually smoke-test the CLI.
4. Commit and push.
5. Start a fresh Claude Code session for the next phase (keeps context clean).
6. Prompt: *"Read `_planning/*.md`. We've completed Phase N. Propose a plan for Phase N+1."*

## Prompts for each phase

### Phase 1 prompt

> We've finished Phase 0 (repo is set up, pyproject.toml is in place, placeholder 0.0.1 is on PyPI).
>
> Read `_planning/SPEC.md` sections: "Project layout", "Data models", "Diagnose prompt", "Generator prompts", "Verification harness", "Storage".
>
> Propose a plan for Phase 1 (core pipeline, end to end, CLI-only — no hooks yet). Goal: `immunize capture < tests/fixtures/cors_error.json` produces all four artifacts with a verified pytest.
>
> Before coding, show me the proposed file list and the implementation order.

### Phase 2 prompt

> Phase 1 is merged. The capture pipeline works end to end.
>
> Now Phase 2: Claude Code hook integration. Read `_planning/SPEC.md` sections "CLI surface > immunize init", "Bundled skill", and "Hook script".
>
> Propose the plan. Include how we'll safely merge into an existing `.claude/settings.json` without clobbering the user's existing hooks.

### Phase 3 prompt

> Phase 2 shipped. Hook-based capture works in Claude Code.
>
> Phase 3: the shell wrapper and git team tier. Read `_planning/SPEC.md` "CLI surface > immunize run" and PLAN.md Phase 3.
>
> The git team tier is mostly documentation, not code. Flag if you think we need explicit sync/merge logic — I expect "just commit the artifacts" is sufficient.

### Phase 4 prompt

> Phases 1–3 are done. Time to polish and launch.
>
> Read `_planning/SPEC.md` section "Demo script" and `_planning/PYPI_PUBLISHING.md`.
>
> Propose Phase 4: test coverage audit, README with demo GIF, PyPI v0.1.0 release (real, not placeholder), and launch material (Hacker News title, first Substack/dev.to post).
>
> Do not record the demo video — I'll do that myself. But draft the voiceover script.

## Things to watch for

**Claude Code will try to be too clever.** If it proposes:

- Adding LangChain → reject, direct SDK only.
- Building a web UI → reject, CLI-first.
- Skipping the verifier with "we'll trust the LLM's test" → reject hard. This is the product.
- Using setuptools for "compatibility" → reject, hatchling.
- Inventing new artifact types → only if it can articulate why Claude Code or Cursor need it.

**Claude Code will sometimes go silent on hard parts.** The verification harness is genuinely tricky (subprocess handling, pytest exit codes, scratch directory cleanup). If it hands you a stub, push back with: *"The verify harness needs to actually run pytest in a subprocess with a timeout, parse exit codes, and correctly distinguish fail-without-fix from pass-with-fix. Show me the complete implementation."*

**Context management for long sessions.** Claude Code's context fills up during long phases. Use `/clear` between phases and re-prime with the prompts above. Don't try to do Phases 1–4 in one session — quality degrades.

## When to abandon plan mode

Plan mode is great for architecture. Once the plan is approved and you're executing, it's often faster to switch to regular mode and let Claude Code write and run code directly. A good rule:

- **Plan mode:** proposing the plan, reviewing big changes, cross-phase decisions.
- **Regular mode:** implementing a specific file, writing tests, fixing a bug.

Switch freely. You don't need to stay in one mode for the whole session.

## If you get stuck

Three common stuck points and how to unblock:

1. **"Claude Code keeps proposing weird architectures."** → Re-prompt: *"Ignore the current approach. The spec in _planning/ARCHITECTURE.md is authoritative. Match it exactly or tell me why it's wrong."*

2. **"Tests keep failing."** → Rather than fighting it, let Claude Code see the failures: *"Run the failing test and show me the full output. Then fix it."* Don't just describe the failure.

3. **"The verifier doesn't verify properly."** → This is the most complex piece. Break it down: *"Write only the part that runs pytest in a subprocess and returns the exit code. Ignore the fix-application logic for now."* Build it up piece by piece.

## The 2-week cadence

Realistic pacing for evenings after coursework and internship:

- **Week 1 Mon–Thu:** Phase 0 + Phase 1 (core pipeline, CLI only).
- **Week 1 Fri–Sun:** Phase 2 (Claude Code hook) + smoke tests.
- **Week 2 Mon–Thu:** Phase 3 (shell wrapper, team tier docs, real-world testing).
- **Week 2 Fri:** Phase 4 polish, demo recording, README.
- **Week 2 Sat:** PyPI release.
- **Week 2 Sun:** Hacker News launch.

Block these on your calendar now. Ship dates create the urgency that makes side projects actually ship.

## After launch

First 72 hours after Show HN is critical. Budget time to:

- Respond to every comment within 2 hours during waking hours.
- Fix any showstopper bug reports same-day.
- Write a follow-up post on day 3 reflecting on the reception.

If it gets traction (say, 500+ stars in a week), start Phase 5 (community registry planning). If it gets crickets, the research and portfolio value are still yours — you've shipped an end-to-end AI-native developer tool, and that's the real win for your September 2026 job hunt.
