# Decision Log
 
 
## 1. Classification + Priority: Parallel over Sequential
**Chose:** Parallel
 
**Over:** Sequential
 
**Because:**
a) Original ticket text is received by both agents - Seq's first agent only gets the original input, afterwards it is only what the agents pass to each other (sequential.py:221). So the priority agent would see a category and not the ticket, and it can't tell a password lockout from a production outage. pass_full_history=True fixes that but then the classifier's answer is sitting in the priority prompt and anchors it.
b) Multiple agents run at the same time -> faster
 
**Cost:** Same - both agents run -> 2 LLM calls. Con - they don't communicate with each other, but they don't have to because category doesn't determine urgency -> urgency is inside ticket -> both agents read it.
 
 
## 2. Merge strategy: STRUCTURED
**Chose:** STRUCTURED
 
**Over:** LLM_SUMMARIZE, or other methods
 
**Because:** it keeps both agents' answers separate and keyed by agent name for no cost, unlike LLM_SUMMARIZE which spends another third LLM call to synthesize which is unnecessary
 
**Cost:** the docs say it gives back a dictionary keyed by agent name. It doesn't - parallel.py:377-381 gives back a JSON string, and the merged response has no structured_output on it at all. So I json.loads it and validate each agent's part myself. See 10.
 
 
## 3. Resolve/escalate gate: code branch over RouterAgent
**Chose:** code branch
 
**Over:** RouterAgent
 
**Because:** 
a) I already have validated enums by this point and RouterAgent can't see them. custom_router only receives the input string, and the built-in router matches words against route descriptions. Either way I would have to turn closed enums back into text so a router could read them again - paying twice for a decision already made.
b) The gate isn't only picking a route. It decides whether to call any agent at all, since an escalated ticket never reaches the resolution agent.
c) Deterministic and testable with no API key - tests/test_gate.py covers every branch.
 
**Cost:** gate is only as good as the enums. A case the categories don't cover falls to the else condition. LLM router might have handled it better and cleaner. This is acceptable because enums are closed and can be controlled unlike LLM, and the else condition escalates, which is the safe direction.
 
 
## 4. Handoff: rejected - no mid-run delegation needed
 
 
## 5. Ticket state: plain Python object carrying ticket_id, status, and history (Continuum doesn't have any primitives or solutions for this)
 
 
## 6. Rejected primitives: 
 
Loop  - re-runs one agent on the same input until a termination condition is met. It's for refinement: draft, critique, redraft. Nothing here needs re-running. Classification doesn't get better on the same second attempt.
I could loop the classifier on low confidence, but I didn't because a second call on the same input mostly returns the same answer, and low confidence is a real signal that we want to escalate on and not retry away.
 
Planner - here LLM decomposes a goal into multiple steps. In our case, steps are fixed and written down: classify, prioritize, resolve/escalate. Paying a model to discover a pipeline we already wrote is a waste. Planner is better to use when steps depend on the input and here they don't.
 
Reflection - agent produces output, a critic grades it, agent retries if the critic says NEEDS IMPROVEMENT. That's two extra calls per ticket for a subjective quality judgement. Our outputs are enum fields. Either the ticket is billing or it isn't - a critic has nothing to improve.
 
DAG (dependency-aware execution) - independent steps run together, dependent steps wait. There's just one dependency case (both agents must finish before the gate) which ParallelAgent already handles.
 
 
## 7. Resolution prompt built in code
**Chose:** build the prompt in pipeline.py from ticket text + category + priority
 
**Over:** chaining the resolution agent after the parallel stage and letting the framework hand it the context
 
**Because:** the parallel stage merges what its two agents said, it doesn't pass the original ticket further down. A chained resolution agent would get the classification JSON and not the customer's words. It needs all three - what the customer wrote, plus the two decisions made about it.
 
**Cost:** the prompt is a fixed string in code, not something the framework puts together. If I add a fourth thing to it I edit that string.
 
 
## 8. output_schema_strict = False (fail soft, don't raise)
**Chose:** the default, False
 
**Over:** True
 
**Because:** when validation fails Continuum logs a warning and returns structured_output=None instead of throwing. The fault run shows why that's what I want - ticket 99's classifier came back with a category outside the enum and died, but the priority agent validated fine and survived. With strict, one bad half would kill a stage that was half correct and I'd throw away a good priority for no reason.
 
**Cost:** the failure is quiet unless something checks for None. That's exactly what the first guard in the gate does, and it's why that guard is first.
 
 
## 9. Three agents, and the gate does the routing
**Chose:** classifier, priority, resolution - agents decide, gate routes
 
**Over:** two agents (classify and prioritize in one call), or five (splitting resolution into write + review)
 
**Because:** two would put category and urgency in the same call, and then they fail together. I'd lose the ability to keep one when the other breaks, which is the whole fault demo. Five adds calls for decisions that don't need a second opinion on closed enums. Where I drew the line: an agent makes a judgement that needs a language model, the gate makes decisions that are plain logic over already validated fields.
 
**Cost:** decisions live in two places - in the agents' schemas and in gate.py. Someone reading only the agents doesn't see the routing rules.
 
 
## 10. Validating each agent's part by hand after the merge
**Chose:** json.loads the merged content, then run coerce_and_validate on each agent's part
 
**Over:** reading structured_output off the merged response
 
**Because:** there is no structured_output on the merged response - ParallelAgent throws away each agent's validated object and merges the raw text instead. I used Continuum's own coerce_and_validate rather than Pydantic's model_validate_json because it never throws, hands back (object, error), and cleans up code fences and wrapper keys - more forgiving of real model output, and it's the framework's parser instead of mine.
 
**Cost:** two different validation paths in one file - the two parallel agents parse strings, the resolution agent reads structured_output directly. That's forced by the framework, not a choice I made for style.
 
 
## 11. Docs and code that didn't match, found while building
All of these I reproduced myself by reading the installed package, not guessed:
1. The docs table says MergeStrategy.STRUCTURED_DICT. The real enum member is STRUCTURED.
2. The docs say STRUCTURED gives back a dictionary keyed by agent name. parallel.py:377-381 gives back a JSON string.
3. The ParallelAgent docstring shows merge_strategy as a constructor argument. It's a dataclass without that field, so passing it raises TypeError. I hit this myself. create_parallel_agent takes it fine.
4. ParallelConfig.merge_strategy defaults to LLM_SUMMARIZE, so STRUCTURED has to be passed in on purpose.
5. output_schema_strict defaults to False - warning plus structured_output=None, no exception.
6. _MAX_STRUCTURED_OUTPUT_RETRIES = 1.
7. executor.py:808 sets content=response.content, which is the model's first answer and not the repaired one from the retry. Since ParallelAgent merges content, anything reading the merge sees the text from before the repair even on a ticket that was repaired. I'm documenting this rather than working around it - the fix would be grabbing structured_output per agent with an on_end hook.
8. Continuum's own settings read .env, but plain os.getenv in my code does not. DEFAULT_LLM_MODEL in .env looked like it was wired up and did nothing. The model is set in the shell instead.
9. Agents log AGENT MEMORY CONFIG: search_memories=True, store_memories=True on every call even though MEMORY_ENABLED=false in .env.
## 12. Confidence came back flat at 0.9 - reporting it, not tuning it away
**Chose:** report what the run actually did and keep the threshold guard
 
**Over:** rewriting the prompt until confidence started varying
 
**Because:** on the real run gpt-4o-mini at temperature 0 gave 0.9 to all five tickets - the same score for a production outage and for "Love your product!". I then ran the same pipeline against genuinely meaningless text ("zzz malformed ticket zzz") to see whether the field moves at all, and it came back 0.7. So confidence does respond to ambiguity, but on this model the whole observed range is 0.7 to 0.9, and 0.7 is not below my 0.7 threshold - that ticket escalated on the category rule instead. Both guards in the gate only push one way, toward escalation. A confidence score this compressed can miss a shaky classification, but it can't cause a wrong auto-resolve. I'm leaving the threshold where it is rather than moving it to <= after seeing one number land on it - fitting a constant to a single observation is how results start lying.
 
**Cost:** a guard that passes its tests but has never fired on real model output, and a threshold sitting exactly on the lowest value I've observed. With more budget I'd sample the same tickets several times and across models to find the real distribution before picking a number, or swap self-reported confidence for something derived from logprobs.