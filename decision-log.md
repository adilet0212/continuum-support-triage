# Decision Log
 
## 1. Classification + Priority: Parallel over Sequential
**Chose:** Parallel
**Over**: Sequential
**Because**: 
1. Multiple agents run at the same time -> faster
2. Original ticket text is received by both agents - Seq's first agent only gets the original input, afterwards it is only what the agents pass to each other.
**Cost: Same - both agents run -> 2 LLM calls. Con - they don't communicate with each other, but they don't have to because category doesn't determine urgency -> urgency is inside ticket -> both agents read it.
 
## 2. Merge strategy: STRUCTURED_DICT
**Chose:** STRUCTURED_DICT
**Over**: LLM_SUMMARIZE, or other methods
**Because**: it returns a structured well ordered dictionary keyed by agent name for no cost unlike LLM_SUMMARIZE which spends another third LLM call to synthesize which is unnecessary
**Cost: returns a raw dict, so have to reach into it and pull out each agent's structured output while LLM_SUMMARIZE would give one synthesized answer.
 
## 3. Resolve/escalate gate: code branch over RouterAgent
**Chose:** code branch
**Over**: RouterAgent
**Because**: already have validated structured fields after two LLM calls and no need to do an extra call for the same task. Branch is deterministic, free, and testable
**Cost: gate is only as good as the enums. Case when the categories don't cover falls to the else condition. LLM router might have handled it better and cleaner. This is acceptable because enums are closed and can be controlled unlike LLM.
 
## 4. Handoff: rejected - no mid-run delegation needed
## 5. Ticket state: plain Python object carrying ticket_id, status, and history (Continuum doesn't have any primitives or solutions for this)

## 6. Rejected primitives: 

**Loop**  - re-runs one agent on the same input until a termination condition is met. It's for refinement: draft, critique, redraft. Nothing here needs re-running. Classification doesn't get better on the same second attempt.
I could loop the classifier on low confidence, but I didn't because a second call on the same input mostly returns the same answer, and low confidence is a real signal that we want to escalate on and not retry away.

**Planner** - here LLM decomposes a goal into multiple steps. In our case, steps are fixed and written down: classify, prioritize, resolve/escalate. Paying a model to discover a pipeline we already wrote is a waste. Planner is better to use when steps depend on the input and here they don't.

**Reflection** - agent produces output, a critic grades it, agent retries if the critic says NEEDS IMPROVEMENT. That's two extra calls per ticket for a subjective quality judgement. Our outputs are enum fields. Either the ticket is billing or it isn't - a critic has nothing to improve.

**DAG** (dependency-aware execution) - independent steps run together, dependent steps wait. There's just one dependency case (both agents must finish before the gate) which ParallelAgent already handles.