# TODO — Pieter Levels Review (2026-04-15)

> "You have real usage data. Let it make the decisions."

## Usage Reality (from bot.db)

| Metric | Number |
|--------|--------|
| Total users | **3** (1 active, 1 one-shot, 1 system/zero) |
| Active user messages | 1,219 over ~50 days |
| Daily avg (last 14 days) | ~15 messages/day |
| Total spend | **$2,122** (~$830 in last 14 days alone) |
| Peak day | $166.70 (Apr 4), $145.85 (Apr 5) |
| Tool calls tracked | 10,714 |
| Top tools | Bash (2941), Read (2325), Edit (1900), WebSearch (1070) |

### Dead Features (zero rows, never used on this instance)

| Table | Rows | Verdict |
|-------|------|---------|
| user_tokens | 0 | Token auth never used |
| scheduled_jobs | 0 | Scheduler never used |
| webhook_events | 0 | Webhooks never triggered |
| project_threads | 0 | Multi-project threads never used |

### Only 1 audit event type exists: `claude_interaction`

The entire audit system tracks one thing. 5 security layers protecting 1 active user.

---

## Phase 0: Decisions Needed

- [x] Pull usage data — **done, see above**
- [ ] **This instance = 1 power user, not 20.** Is the 20-person review happening on a different instance? If so, pull that data too
- [ ] **$830/14 days = ~$1,770/month burn.** Is that acceptable? Is there a budget?
- [ ] **Internal tool AND product path** — but this instance is essentially a single-user power tool right now
- [ ] **Agentic mode confirmed as primary** — Classic mode is likely dead weight here

---

## Phase 1: Delete Dead Code (Safe Kills)

These features have **zero usage on this instance**. Delete the code, keep git history.

- [ ] **Delete token auth system** — `user_tokens` table empty, `src/security/auth.py` TokenAuthProvider unused
- [ ] **Delete scheduler** — `scheduled_jobs` empty, remove `src/scheduler/` (APScheduler dep can go too)
- [ ] **Delete webhook system** — `webhook_events` empty, remove `src/api/server.py` webhook routes, `src/events/handlers.py` webhook handling
- [ ] **Delete project threads** — `project_threads` empty, remove `src/projects/`
- [ ] **Delete or gate Classic mode** — if Agentic is the path, kill `src/bot/handlers/command.py` (1238 lines), `callback.py` (1316), `message.py` (1065)
- [ ] **Simplify EventBus** — with no webhooks or scheduler, what's left subscribing?

**Conservative estimate: ~4,000-6,000 lines removed, 3 deps dropped**

---

## Phase 2: Simplify the Core

What remains after Phase 1 is: Telegram bot → Claude SDK → SQLite. Make that path simple.

- [ ] **Flatten Claude integration** — `facade.py` → `sdk_integration.py` → SDK client. Should be 1 file
- [ ] **Simplify storage** — 5 files → 2 (schema + queries). You're storing messages and sessions, not running an ORM
- [ ] **Simplify security** — whitelist + rate limit is enough. Drop the 5-layer chain to 2
- [ ] **Reduce config** — 5 config files with feature flags, env detection, API settings. For a single-purpose bot, 1 settings file is enough
- [ ] **Audit `formatting.py`** (684 lines) — that's a lot of formatting code. What's actually used?

---

## Phase 3: Product Path (When Ready)

_Only after Phase 1-2 make the codebase manageable._

- [ ] **Get the 20-person review data** — is there a separate instance? What's their feedback?
- [ ] **One-line pitch** — "Claude Code from your phone" or "AI dev agent for Telegram teams"
- [ ] **Landing page + demo GIF** — show, don't tell
- [ ] **One-command deploy** — `docker run` or Railway template
- [ ] **Usage analytics dashboard** — you already have the SQLite data, just surface it
- [ ] **Pricing model** — usage-based with margin on Claude API? You're spending $1,770/mo for 1 user

---

## OpenAI Compat API Backlog

_API is confirmed in use. Cost tracking was missing — now fixed (see below)._

- [x] Delta-only streaming
- [x] **Cost tracking for API requests** — API endpoint was not recording costs, messages, or tool usage. Fixed: `Storage.save_claude_interaction()` now called for both streaming and non-streaming paths
- [ ] `reasoning_content` + `<think>` tags (stashed, being worked on in pullbot9000)
- [ ] Keep-alive comments during tool execution
- [ ] Tool call streaming (OpenAI format)
- [ ] Streaming error events
- [ ] Usage in final chunk
- [ ] `stop` vs `length` finish reason

---

## Stashed Changes

```
git stash list  →  "WIP: openai compat reasoning_content + sdk + main changes"
```

Being worked on in another copy of the repo. Don't touch here.

---

## Repo Consolidation

Two clones exist: `pullbot9000` (API mode) and `pullbot9001` (Telegram mode). They don't need to be separate repos.

- [x] **Confirmed: same codebase, same schema, slightly diverged** — 9000 has 1 extra commit + Makefile `tunnel`/`serve` targets
- [ ] **Consolidate to one repo with two `.env` files** — `.env.telegram` and `.env.api`, each with its own `DATABASE_URL`
- [ ] **Merge 9000's Makefile targets** (`tunnel`, `serve`) into the main Makefile
- [ ] **Cherry-pick `22bef2e`** (thinking/reasoning commit) from 9000 when ready
- [ ] **Archive pullbot9000** after migration

## The Levels Take

1. **1 user spending $2,122 is either your best customer or a cost center.** Know which.
2. **4 entire subsystems (tokens, scheduler, webhooks, project threads) were built and never used.** That's weeks of dev time on zero-value features.
3. **The bot works.** 1,219 messages, 10,714 tool calls. The core is solid. Stop adding, start subtracting.
4. **$60/day average API spend needs a business model** — even internally, someone's paying that bill.
5. **The API had no cost tracking.** Fixed now — but unknown spend has been accumulating since March 18.
6. **Delete the dead code this week.** It's the highest-ROI work: less to maintain, less to understand, less to break.
7. **One repo, two env files.** Stop maintaining two clones of the same code.
