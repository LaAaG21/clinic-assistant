# Clarification before ordinary actions (#68)

`clarify` takes a validated `IntentResult` and returns the original state with
an optional follow-up question. The rules run in this order:

- Emergency labels bypass ordinary clarification for the separate emergency handoff.
- Uncertain or `other` requests ask what help the user needs.
- Availability requests ask for a date and a doctor or specialty if missing.
- Booking requests ask for a missing slot ID.
- Cancellation requests ask for a missing appointment ID.
- Complete requests pass through unchanged.

Run `uv run --locked pytest tests/test_clarification.py -q`.
