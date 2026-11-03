# Clarification before ordinary actions (#68)

The issue assignee confirmed #63/#68's state and rules on 2026-11-03: an intent,
uncertainty flag, optional doctor/specialty/date/slot/appointment details, and
questions for missing availability date plus doctor/specialty, booking slot ID,
or cancellation appointment ID. This records the assignee's decision rather than
claiming a completed #38 team walkthrough.

`clarify(classification)` is pure: it accepts #63's read-only validated state and
returns `Clarification(original_state, question)`. A null question forwards the
unchanged state; a question requires clarification before action. No IDs, doctors,
dates, or user intent are invented or changed. Uncertainty takes priority over
otherwise complete ordinary details; `other` asks what clinic help is needed.
Emergency labels bypass ordinary clarification for the separate emergency handoff.
This is not an emergency detector; the actual guard still precedes classification.

The structural protocols describe the approved state, not another model adapter
or a duplicate classification parser. Production classification owns validation;
the helper owns only missing-detail questions. Identifiers remain untrusted and
must be resolved by later action consumers. No model call, storage operation,
booking, cancellation, or final graph routing is added.

Run `uv run --locked pytest tests/test_clarification.py -q` plus the shared quality
checks. Unit fixtures follow the approved #63 shape and are driven by configured
#46 fake output. They cover ambiguity, each missing field, valid complete cases,
emergency handoff, unchanged identity, repeated decisions, no additional model
calls, and guarded database access.

Draft until #63 merges and its real classifier integration can be included in
the shared suite. The fixture tests do not claim that dependency has merged.
An isolated check loaded #63's actual pending classifier/state code and verified
missing availability details produce a question, a complete booking passes
through, and an uncertain cancellation asks for clarification, retaining the
same state object with one fake call. No dependency code is copied into this PR.
Verified 2026-11-03: 13 focused cases and 233 total tests passed with real
PostgreSQL enabled; clarification coverage 100%, overall coverage 98.13%.
Ruff lint/format and strict Mypy passed. The direct classifier integration must
join the shared suite after #63 merges.
