# Synthetic clinic documents and patient messages

Issue: #42. Directory: [`src/clinic_assistant/demo_data/`](../../src/clinic_assistant/demo_data/).

Reusable **synthetic** development and demonstration fixtures for the fictional
Cedar Grove Clinic. They contain no real patient information; phone numbers use the
reserved 555-01xx range and every policy is invented. Each document states this in
its opening paragraph, and the message file sets `"synthetic": true`.

The files live inside the package so the #25 Docker build (`COPY src`) and the
built wheel include them automatically; no extra copy step is needed.

## Clinic documents

UTF-8 Markdown in the #21 loader format. The filename is the stable source name.

| Source name | Content |
|---|---|
| `clinic-hours.md` | Opening days and times, reception phone hours, holiday closures. |
| `appointments.md` | Appointment length, booking channels, same-day and cancellation approval, arrival time. |
| `visiting-the-clinic.md` | Parking, wheelchair access, accepted insurance, offered specialties. |
| `urgent-care.md` | Not an emergency service; no diagnosis or treatment advice in chat. |

Content is adapted from the #5 retrieval research documents
(`experiments/retrieval/documents/`), which stay unchanged as that experiment's
evidence; the demo set adds headings and a few extra paragraphs so passage splitting
(#28) has more than one passage per document.

## Patient messages

`patient_messages.json` lists one example per scenario. Each entry has an `id`, a
`scenario` label, the patient `text`, the `expected_intent` and
`expected_response_type` from the proposed #6 contract, the `expected_sources` a
grounded answer would cite, and a short `note`.

| Scenario | Example text | Intent | Response type |
|---|---|---|---|
| `supported_clinic_question` | When does the clinic open? | `clinic_question` | `answer` (cites `clinic-hours.md`) |
| `unsupported_clinic_question` | Does the clinic accept Maple insurance? | `clinic_question` | `unsupported` |
| `availability` | Which dermatology appointments are free on 2026-11-10? | `find_slots` | `slots` |
| `booking` | Please book slot_seed_derm_20261110T1000. | `book` | `action` |
| `cancellation` | Please cancel my appointment appt_demo. | `cancel` | `action` (`pending_approval`) |
| `emergency` | I have sudden chest pain and I can't breathe properly. | `emergency` | `emergency` |

The availability and booking examples line up with the #29 seed data when it is
loaded with `SEED_BASE_DATE=2026-11-10`. `appt_demo` is the illustrative ID from the
#6 walkthrough; no appointment is seeded. Expected values follow #6, which is still
a proposal: if the contract changes, update these examples with it.

These are examples only. There is no scenario runner and nothing executes a
workflow; that is outside #42.

## Why separate from unit-test fixtures

Unit tests create tiny temporary files in `tmp_path` that exist only for one
assertion and are shaped to hit an edge case. Demo fixtures are shared, stable,
realistic data for demonstrations and manual checks across features. Keeping them
apart means a test can change its throwaway input freely, and a demo edit cannot
silently break or weaken an unrelated unit test.

## Verification

```sh
uv run --locked pytest tests/test_demo_data.py -v
```

The test loads every document through `load_document` (#21), checks each source name
equals its filename, splits it with `split_document` (#28), validates each message
text against `PatientMessageRequest`, and checks every example's intent and response
type against its scenario label and the #6 values. It does not run workflows.

Verified 2026-11-05 on Windows, Python 3.12: all four documents loaded with source
names `appointments.md`, `clinic-hours.md`, `urgent-care.md` and
`visiting-the-clinic.md` (each source ID equal to its filename); 9 demo-data tests
passed. `uv build --wheel` included all `demo_data/` files. Ruff, format and strict
Mypy were clean; the full suite passed apart from the real-PostgreSQL health test,
which needs `TEST_DATABASE_URL` and was not run.
