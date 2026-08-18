# Continuum Support Triage

A multi-agent customer support pipeline built on
[Continuum](https://github.com/shyftlabs/continuum) 1.2.0.

A ticket comes in. A classifier and a priority agent read it at the same time,
a deterministic gate decides whether it can be answered automatically, and a
resolution agent writes the reply only for the tickets that qualify. Every
agent decision is a Pydantic model validated by the framework, and every state
change is recorded with a reason, so you can read back exactly why any ticket
ended up where it did.

```
                  ┌──────────────┐
   ticket ───────►│  classifier  │──┐
      │           └──────────────┘  │   ParallelAgent
      │           ┌──────────────┐  │   MergeStrategy.STRUCTURED
      └──────────►│   priority   │──┤
                  └──────────────┘  │
                                    ▼
                              ┌──────────┐
                              │   gate   │  plain Python, no LLM
                              └──────────┘
                               │        │
                     resolve   │        │  escalate
                               ▼        ▼
                      ┌────────────┐   (human)
                      │ resolution │
                      └────────────┘
```

---

## Setup

Requires **Python 3.13+** (Continuum's floor) and an OpenAI API key.

**Windows (PowerShell):**

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
$env:OPENAI_API_KEY="sk-..."
```

**macOS / Linux:**

```bash
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY="sk-..."
```

No Docker required. `MEMORY_ENABLED`, `SESSION_ENABLED`, `LANGFUSE_ENABLED`
and `TEMPORAL_ENABLED` are all `false`, so Redis, Qdrant and Langfuse never
start. This pipeline is stateless per ticket and does not need them.

`.env.example` lists what is needed. `LLM_MAX_RETRIES` controls Continuum's own
provider-level retries and is separate from `_MAX_STRUCTURED_OUTPUT_RETRIES`,
which governs the schema-repair attempt after a validation failure - two
different mechanisms that are easy to confuse.

### Choosing the model

`DEFAULT_LLM_MODEL` selects the provider. It has to be set **in the shell**,
not in `.env` - see the friction section for why.

```powershell
$env:DEFAULT_LLM_MODEL="gpt-4o-mini"   # real run, costs money
```

If it is unset, the code falls back to `mock/gpt-4o-mini` and runs against
canned fixtures with no network calls at all. That default is deliberate: it
means a fresh clone runs and produces output without a key.

---

## Running it

```bash
python run_tickets.py              # the five sample tickets
python -m src.main --fault         # the forced schema-failure demo
python -m pytest                   # 17 gate tests, no API key needed
```

`run_tickets.py` is a thin wrapper over `python -m src.main`. Either works;
the `-m` form is what the package layout expects, since every import is
absolute (`from src.gate import decide`) and needs the repo root on the path.

Saved output from every run is in `logs/`:

| File | What it is |
|---|---|
| `real_run.txt` | the five tickets against gpt-4o-mini |
| `mock_run.txt` | the same five against fixtures, no API calls |
| `mock_fault_run.txt` | the forced validation failure |
| `real_ambiguity_probe.txt` | one ticket of meaningless text against the real model |
| `pytest_run.txt` | the gate test suite |

---

## Results

Measured on `gpt-4o-mini` at temperature 0. Nothing here is estimated.

| # | Ticket | Category | Priority | Confidence | Outcome |
|---|---|---|---|---|---|
| 1 | Cannot access my account | account | medium | 0.9 | escalated |
| 2 | Charged twice this month | billing | high | 0.9 | escalated |
| 3 | API returning 500 errors | technical | critical | 0.9 | escalated |
| 4 | How do I export my data? | general | low | 0.9 | resolved |
| 5 | Love your product! | feedback | low | 0.9 | resolved |

Twelve LLM calls for five tickets, not fifteen - the resolution agent only runs
on the two tickets the gate cleared. I ran the whole set twice against the live
model and got identical categories, priorities and outcomes both times.

The full audit trail for each ticket is in the log, for example:

```
--- ticket 1: escalated ---
  received     ticket received
  classified   classifier output validated
  prioritized  priority output validated
  escalated    not in the auto-resolvable set
  -> account / medium (confidence 0.9)
```

### One measured result I did not like, and kept anyway

Confidence came back as **0.9 on all five tickets** - the same score for a
production outage and for "Love your product!", even though both the schema
description and the agent instructions ask the model to lower it when a ticket
is ambiguous.

So I checked whether the field moves at all. I ran the pipeline against
genuinely meaningless text (`zzz malformed ticket zzz`) and got **0.7**
(`logs/real_ambiguity_probe.txt`). Confidence does respond to ambiguity, but on
this model the entire observed range is 0.7 to 0.9 - and 0.7 is not below my
0.7 threshold, so that ticket escalated on the category rule instead.

I left the threshold at `< 0.7` rather than changing it to `<=` after watching
one number land exactly on it. Fitting a constant to a single observation is
how results start lying. Both gate guards only push one way, toward escalation,
so a compressed confidence score can miss a shaky classification but cannot
cause a wrong auto-resolve.

---

## Design decisions

The short version of each choice is below. All twelve decisions, including the
primitives I looked at and rejected, are in [`decision-log.md`](decision-log.md).

### Classification and priority run in parallel, not in sequence

Both agents need the raw ticket text, and that is the whole reason for this
choice. Under Continuum's default SequentialConfig the second stage only gets
what the first stage produced (sequential.py:221), so the priority agent would
see the word "account" and nothing else. You cannot tell a password lockout
from a production outage from a category alone. There is a `pass_full_history`
flag that puts the ticket text back, but it also puts the classifier's answer
into the priority prompt, and I did not want the priority agent reading a
verdict before making its own.

It costs the same either way - two LLM calls - so this is not a saving. The two
branches also cannot talk to each other, which is fine here, because the
category does not decide the urgency. The urgency is in what the customer
wrote, and both agents read that.

### The two branches are merged with MergeStrategy.STRUCTURED

The other option was LLM_SUMMARIZE, which is what ParallelConfig uses by
default. That spends a third LLM call to turn two structured answers into
prose, which I would then have to parse back into fields. STRUCTURED keeps both
answers separate and keyed by agent name, and costs nothing.

One thing to flag: the docs say STRUCTURED gives back a dictionary keyed by
agent name. It does not. `parallel.py:377-381` returns a JSON string, and the
merged response has no `structured_output` on it at all - the framework throws
away each branch's validated object and merges the raw text. So I parse the
merged content myself and validate each agent's part with Continuum's own
`coerce_and_validate`. More on this in the friction section below.

### The resolve/escalate decision is a code branch, not a RouterAgent

By the time this decision gets made I already have validated enums - a category
and a priority that Pydantic has checked. A RouterAgent cannot see any of that.
`custom_router` only receives the input string, and the built-in router matches
words against route descriptions. Either way I would have to flatten closed
enums back into text so a router could read them again, which is paying an LLM
to re-derive a decision that has already been made.

The second reason is that the gate does more than pick a route. It decides
whether to call any agent at all - an escalated ticket never reaches the
resolution agent, so five tickets cost 12 calls instead of 15. And because it
is plain logic over validated fields, I can test every branch of it with no API
key. `tests/test_gate.py` does exactly that.

The cost is that the gate is only as good as the enums. A ticket that fits none
of the categories falls through to the else branch, and an LLM router might
have handled that more gracefully. I accepted this because the enums are closed
and under my control, and because the else branch escalates - which is the safe
direction to fail in.

### Three agents, and the gate does the routing

Two agents would have meant classifying and prioritizing in one call. That
couples them: when one fails, both fail, and I lose the ability to keep the good
half. That ability is the whole point of the fault demo - ticket 99's classifier
comes back with a category outside the enum and dies, while the priority agent
validates fine and survives. Five agents would have meant splitting resolution
into a writer and a reviewer, which adds calls to second-guess decisions made
over closed enums.

The line I drew: an agent makes a judgement that needs a language model, and
the gate makes decisions that are plain logic over fields that have already been
validated. The cost is that the routing rules live in `gate.py` and not in the
agents, so reading the agents alone does not tell you how a ticket gets routed.

### Primitives I did not use

Handoff, Loop, Planner, Reflection and DAG were all considered and rejected -
the reasoning for each is in `decision-log.md`. The short version: nothing here
needs an agent to hand off mid-run, nothing improves on a second identical
attempt, the steps are fixed and written down rather than discovered, the
outputs are enum fields with nothing for a critic to improve, and the only
dependency in the graph is one that ParallelAgent already handles.

---

## Error handling

**The scenario: an agent returns output that fails schema validation.**

`python -m src.main --fault` runs a synthetic ticket whose mocked classifier
response has `"category": "urgent_thing"` - not a member of `TicketCategory`.
The full log is `logs/mock_fault_run.txt`. What happens:

1. Pydantic rejects the category. Continuum logs a warning and returns
   `structured_output=None` rather than raising, because `output_schema_strict`
   defaults to `False`.
2. The priority agent, running in the other branch, validates fine and survives.
3. The pipeline's per-branch handler logs which agent failed and why, and leaves
   that slot empty.
4. The gate's first guard sees the empty slot and escalates.
5. The ticket reaches a terminal state with a reason, and no `classified` entry
   in its history - because classification genuinely did not happen.

```
--- ticket 99: escalated ---
  received     ticket received
  prioritized  priority output validated
  escalated    classification or priority failed schema validation
```

Soft-fail is the point here. Under `output_schema_strict=True` one bad branch
would take down a stage that was half correct, and a perfectly good priority
would be thrown away for no reason.

Two more failure paths exist but are not separately demonstrated: if **both**
branches fail, the merged content is a plain-text notice rather than JSON, so
the `json.loads` is guarded and both slots stay empty (the same gate guard
catches it); and the resolution agent can return `resolved=False`, which
escalates rather than sending a reply it cannot stand behind.

**What I did not build:** timeout and rate-limit handling. Continuum has retry
and circuit-breaker behaviour of its own, but I have not exercised it here. The
mock provider is where I would inject it - raising a provider-level exception
from `MockProvider.acomplete` would drive that path through the same seam, and
it is a small fixture change rather than a redesign. I chose to prove one
scenario end to end rather than claim four.

---

## Testing

`python -m pytest` runs 17 tests over `gate.py` with no API key and no network.
They cover both guards (a missing slot in either direction, confidence below
threshold, and confidence sitting exactly on the threshold), every branch of the
auto-resolvable set, and the fact that `decide()` does not mutate the ticket -
transitions are recorded by the pipeline, not the gate.

The gate is the component most worth testing because it is the one that decides
whether a customer gets an automated answer or a human. It is also the component
whose testability is the reason it is not a RouterAgent.

---

## Assumptions

- **I added a fifth category, `feedback`.** The assignment lists categories with
  "e.g.", so the set is open. Ticket 5 asks for nothing at all, and without a
  category for it the system either escalates a compliment to a human or
  auto-answers something that was not a request. A fifth category gives it a
  correct terminal state without inventing a third outcome type.
- **Auto-resolvable means `feedback` at any priority, or `general` at low
  priority.** Everything else escalates. Billing, technical and account tickets
  need account access, a refund, or an engineering fix - none of which a
  first-line agent has.
- **Escalation is the safe default.** Both gate guards only push one way. A
  wrong escalation costs a human a few minutes; a wrong auto-resolve sends a
  confident answer to someone whose production system is down.
- **Confidence is self-reported by the model** and I treat it as a signal, not a
  calibrated probability. See the results section.
- **State is per-ticket and in-memory.** No persistence, no cross-ticket memory.
- **`temperature=0` on all three agents**, so a repeat run is reproducible.

---

## What Continuum's docs did not tell me

All of these I reproduced myself by reading the installed package, not inferred.

1. The docs table says `MergeStrategy.STRUCTURED_DICT`. The real enum member is
   `STRUCTURED`.
2. The docs say STRUCTURED returns a dict keyed by agent name.
   `parallel.py:377-381` returns a JSON string.
3. The `ParallelAgent` docstring shows `merge_strategy` as a constructor
   argument. It is a dataclass without that field, so passing it raises
   `TypeError`. `create_parallel_agent` accepts it fine - that is what I use.
4. `ParallelConfig.merge_strategy` defaults to `LLM_SUMMARIZE`, so STRUCTURED
   has to be passed in deliberately.
5. `output_schema_strict` defaults to `False`: a warning plus
   `structured_output=None`, never an exception.
6. `_MAX_STRUCTURED_OUTPUT_RETRIES = 1`.
7. `executor.py:808` sets `content=response.content`, which is the model's first
   answer and not the repaired one from the retry path. Since ParallelAgent
   merges `content`, anything reading the merge sees the text from before the
   repair even on a ticket that was repaired. I am documenting this rather than
   working around it - the fix would be capturing `structured_output` per agent
   with an `on_end` hook.
8. Continuum's own settings read `.env`, but plain `os.getenv` in application
   code does not. `DEFAULT_LLM_MODEL` in `.env` looked wired up and did nothing.
   The model is set in the shell instead.
9. Agents log `AGENT MEMORY CONFIG: search_memories=True, store_memories=True`
   on every call even though `MEMORY_ENABLED=false`.

Where I worked around something, it is because the framework's actual behaviour
required it - the manual parse after the merge is the only place, and it uses
Continuum's own `coerce_and_validate` rather than a parser of mine.

---

## What I would do next

- **Replace or drop self-reported confidence.** The observed range on this model
  is 0.7 to 0.9. I would sample the same tickets several times and across models
  to find the real distribution before trusting a threshold, or derive
  confidence from logprobs instead. A guard that looks like a safety net and
  is not one is worse than no guard.
- **Capture `structured_output` per branch with an `on_end` hook**, which fixes
  finding 7 and removes the manual parse after the merge.
- **Inject a provider-level timeout** through the mock seam to exercise
  Continuum's retry and circuit-breaker path.
- **Persist state.** Right now a ticket's history dies with the process. This is
  where `MEMORY_ENABLED` and a real store would earn their keep - I left them
  off deliberately because a stateless per-ticket pipeline gains nothing from
  them, and adding Docker infrastructure to demonstrate an unused feature is
  worse judgement, not better.
- **Widen the evaluation.** Five tickets and one fault case is a demo, not a
  measurement. The next step is a labelled set and per-field accuracy against
  it, the same way I would evaluate any extraction pipeline.

---

## Layout

```
run_tickets.py            CLI entry point for the five sample tickets
requirements.txt
decision-log.md           all twelve decisions, chose/over/because/cost
src/
  schemas.py              Pydantic output schemas and the closed enums
  state.py                TicketState dataclass, transitions and history
  gate.py                 the resolve/escalate decision, no LLM
  pipeline.py             the three agents, the parallel stage, the flow
  main.py                 the sample tickets and the --fault flag
  mock_provider.py        a mock LLM provider via Continuum's register_provider
  fixtures.py             canned responses, including the invalid one
  smoke_test.py           checks a real key and a real call work
  mock_smoke.py           checks the mock seam works, no API calls
tests/
  test_gate.py            17 tests over the gate, no API key needed
logs/                     saved output from every run above
```
