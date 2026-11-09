# Concurrent booking verification (#64, U06)

`tests/test_concurrent_booking.py` proves that genuinely simultaneous booking
attempts cannot create two active bookings for one slot. It runs the real
`booking_outcomes.book_request` path (#66 over #61's `insert_booking`) against
real PostgreSQL. No race, connection or model is mocked.

## Method

- **Independent contenders.** Each attempt runs in its own thread with its own
  connection and transaction from the shared `approval_db` fixture.
- **Synchronization.** A `threading.Barrier` releases all contenders into
  `book_request` together.
- **Observed overlap.** The first contender to finish keeps its transaction open
  (up to 0.5 s, under the 1000 ms statement timeout). An autocommit monitor
  connection polls `pg_stat_activity` until `pg_blocking_pids` shows the peers
  waiting on it. The test asserts at least one peer was blocked. This shows
  in the database that the attempts overlapped; it is not inferred from timing.
- **Results after completion.** Outcomes and the final active-booking count are
  read on a fresh connection only after every contender has finished.

## Scenarios

| Test | Contenders | Expected |
| --- | --- | --- |
| different requests, same free slot | 2 and 4 | one `appointment_booked`, the rest `slot_unavailable`; exactly one active booking owned by the winner's conversation; losers keep `booking_id` NULL |
| same request retried at once | 3 | every attempt returns the same `appointment_booked` booking ID; exactly one booking row for the slot |

Each scenario repeats three rounds with a new synthetic slot, conversations and
requests, so one lucky ordering cannot pass. Every round also checks that the
fixture's unrelated bookings (`s1`/`b1`, free `s2`) are unchanged.

## Commands

No model key is needed: the test never touches the model adapter.

```bash
docker run -d --name clinic-u06-pg -e POSTGRES_USER=clinic -e POSTGRES_DB=clinic -e POSTGRES_PASSWORD=u06test -p 127.0.0.1:55432:5432 postgres:17.6
```

```bash
TEST_DATABASE_URL=postgresql://clinic:u06test@127.0.0.1:55432/clinic uv run --locked pytest tests/test_concurrent_booking.py -v -s
```

`-s` prints one `U06 slot=... active_bookings=... outcomes=[(request, code,
blocked_peers), ...]` line per round as the retained evidence.

## Recorded results

- Revision: this change on top of `6fcaca4` (#66), PostgreSQL 17.6, Python 3.12,
  `MODEL_BACKEND` unset (no OpenAI key).
- 3 passed in about 2.8 s. Five consecutive reruns all passed.
- Every round ended with `active_bookings=1`. With 2 contenders the winner saw
  1 blocked peer; with 4 contenders it saw 3. Same-request retries returned one
  shared booking ID with 1 blocked retry on the request row lock.
- Control: with the `ON CONFLICT ... DO NOTHING` guard removed from
  `insert_booking`, both different-request tests fail (the losers surface a
  unique violation instead of `slot_unavailable`). The partial unique index
  still prevented a second active booking.

## What this proves that sequential calls cannot

Two sequential calls only show that the second call sees the first call's
committed row. Synchronized contenders whose transactions are seen blocking on
each other show that the conflict is decided by PostgreSQL's active-slot unique
index and the request row lock while both transactions are in flight. A
check-first/insert-later implementation would pass sequential tests but fail
here.
