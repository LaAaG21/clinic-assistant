# Staff interrupt/resume — proposed findings (issue #4)

**Question.** Can a workflow durably wait for a staff decision before acting, and
return explicit waiting/final messages without calling a real model?

**Official sources first.** [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)
documents `interrupt()`, the same `thread_id`, `Command(resume=...)` and node replay.
[PostgreSQL checkpoint setup](https://docs.langchain.com/oss/python/langgraph/add-memory#use-in-production)
documents `PostgresSaver` and first-use `setup()`.
[Issue #4](https://github.com/LaAaG21/clinic-assistant/issues/4) defines this spike;
[issue #3](https://github.com/LaAaG21/clinic-assistant/issues/3) defines the related
container-restart persistence experiment.

**Options.** A boolean returned by an LLM cannot suspend execution. Process-local
waiting or in-memory checkpoints lose pending work on restart. A dynamic LangGraph
interrupt with PostgreSQL checkpoints fits the required durable pause. SQLite and
in-memory alternatives were excluded by the issue's scope.

**Versions.** Python 3.12; `langgraph==1.2.19`,
`langgraph-checkpoint-postgres==3.2.0`, `psycopg[binary,pool]==3.3.6`;
Docker Compose uses PostgreSQL 17. Direct Python dependencies are pinned; the base
images and transitive dependencies are not fully locked. The CLI prints installed
versions with every run.

**Reproduce.** From `experiments/staff_approval`, run
`docker compose up -d --wait db`, `docker compose build demo`, then
`docker compose run --rm demo verify`. The experiment README includes separate
`start`, `inspect` and `resume` container commands and pending/decision API examples.
Save the emitted `PENDING_API_RESPONSE`, `SAVED_STATE`, `SIMULATED_API_DECISION`
and final state for both decisions as verification evidence.

**Design findings.** `propose → staff_review → simulate_action | reject` keeps the
fake LLM in a completed node before the interrupt. Waiting is stored as explicit
patient-visible state before pausing. On resume `staff_review` starts again from
its beginning; `propose` is already checkpointed and does not run again in this
normal path. Only approval routes to the simulated action. Rejection has its own
patient-visible outcome. These expected traces are checked by the runnable spike's
state assertions and can be inspected in console node traces when run successfully.

**Verification status (2026-11-02).** Dependencies installed in a local Python
3.12.15 environment; Python source compilation and Compose configuration validation
passed. End-to-end PostgreSQL verification could not run in the preparation
environment: Docker's Linux engine pipe was unavailable, and native Python import
failed because Windows Application Control blocked `xxhash`'s extension DLL. No
successful pause/resume or persistence observation is claimed. The commands and
assertions above are supplied for a Docker-enabled developer machine; capture actual
output before marking the issue's runtime verification criteria complete.

**Replay and side-effect risks.** Code before `interrupt()` can run again because
the interrupted node restarts instead of continuing an in-process stack. Keep it
pure or idempotent. Even a later action node may replay after a crash between an
external write and checkpoint commit. PostgreSQL checkpoints alone do not provide
exactly-once appointment writes; production needs a unique operation key, database
constraints/transactions and possibly an outbox. Do not wrap `interrupt()` in a
broad exception handler. Keep interrupt order stable across deployed graph versions.

**Comparison with #3 / recommendation (proposed).** Both experiments should use the
same server-owned thread identity and durable PostgreSQL database. This spike checks
pending interrupt state and reconnect behavior; #3 additionally requires restarting
the application container while retaining DB storage and continuing conversation
state. Neither issue blocks the other. No #3 results or team agreement were supplied;
comparison of observed restart evidence and the five-minute share-out remain team
work. Discuss thread ownership, checkpoint migration, concurrency and action
idempotency, then record the agreed decision in `docs/adr/`. Do not label this proposal
accepted before that meeting.
