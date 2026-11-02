# Staff approval spike — issue #4

This standalone experiment uses synthetic data, fixed fake-LLM replies and real
PostgreSQL checkpoints. It needs no OpenAI key. It does not book appointments or
implement HTTP endpoints. Run commands from this directory in the VS Code terminal.

Preparation checks passed for Python source compilation and Compose configuration.
Runtime verification remains pending: Docker's engine was unavailable and Windows
Application Control blocked a native Python dependency in the preparation environment.
Run the following verification commands before marking the issue complete.

## Quick verification (Docker Desktop running)

```powershell
docker compose up -d --wait db
docker compose build demo
docker compose run --rm demo verify
```

`verify` asserts that each request really interrupts before its action, closes the
checkpoint connection, rebuilds the graph, restores the saved state, and resumes
separate approval and rejection threads. It prints the pending patient response,
saved interrupt and next node, decision payload and final patient response. Expected
node traces are `propose, staff_review, staff_review, simulate_action` for approval
and `propose, staff_review, staff_review, reject` for rejection. Only approval sets
`action_performed` to true. Each verification run generates fresh IDs.

## Pause and resume across separate containers

```powershell
docker compose run --rm demo start --thread issue4-approve-1
docker compose run --rm demo inspect --thread issue4-approve-1
# Copy pending_id from PENDING_API_RESPONSE into the following command:
docker compose run --rm demo resume --thread issue4-approve-1 --pending-id '<pending_id>' --decision approve --reason 'Synthetic slot confirmed by staff'

docker compose run --rm demo start --thread issue4-reject-1
docker compose run --rm demo inspect --thread issue4-reject-1
docker compose run --rm demo resume --thread issue4-reject-1 --pending-id '<pending_id>' --decision reject --reason 'Synthetic slot unavailable'
```

These are new application containers against the same database volume. For repeated
runs use fresh thread IDs. `start` refuses to overwrite a saved thread; `resume`
rejects a mismatched pending ID, empty reason, unknown decision, or completed thread.
Capture the console output for the spike share-out. Do not remove the database volume
between pause and resume. `docker compose down` stops the experiment and retains it.

Alternatively use Python 3.12, install `requirements.txt`, set `DATABASE_URL` to a
dedicated PostgreSQL database, and run `python demo.py verify`. `saver.setup()`
creates LangGraph's checkpoint tables; use a database role with DDL permission for
this local experiment. A production deployment should run setup as a migration.

## Proposed API handoff (examples, no HTTP routes implemented)

Initial request creates a server-owned thread ID and pending ID. The waiting result
can be returned as HTTP 202:

```json
{
  "thread_id": "issue4-approve-1",
  "pending_id": "<server-generated UUID>",
  "interrupt_id": "<LangGraph interrupt ID>",
  "status": "pending_approval",
  "proposal": "Propose synthetic same-day appointment SYNTHETIC-SLOT-1 for staff review.",
  "patient_message": "Your request is waiting for staff approval. No appointment has been booked."
}
```

Proposed staff request: `POST /pending-approvals/{pending_id}/decision`:

```json
{
  "decision": "approve",
  "reason": "Synthetic slot confirmed by staff"
}
```

The authenticated server would resolve the pending ID to the authorized thread and
its current interrupt, validate that it is still waiting, and execute:

```python
graph.invoke(
    Command(resume={"pending_id": pending_id, "decision": "approve", "reason": reason}),
    config={"configurable": {"thread_id": stored_thread_id}},
)
```

For this single-interrupt graph the payload resumes the only pending interrupt.
Multiple simultaneous interrupts require explicit interrupt-ID mapping. Never trust
a client-supplied thread ID as authorization. Production also needs staff identity,
an audit record, atomic claim/serialization of decisions and idempotent booking writes.
The CLI's pending check alone does not prevent concurrent staff decisions.

The final response has `status: approved` and the message “Staff approved your request.
The synthetic booking was simulated.” Rejection returns `status: rejected` and
“Staff declined your request. No appointment has been booked.” The staff reason is
preserved in checkpoint state; this demo does not expose internal reasons to patients.
