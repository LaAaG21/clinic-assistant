# Synthetic demo data (#42)

**Synthetic development and demonstration fixtures. No real patient information.**
Everything here describes the fictional Cedar Grove Clinic; phone numbers use the
reserved 555-01xx range and all policies are invented.

- `clinic_documents/` — UTF-8 Markdown clinic documents in the #21 loader format.
  The filename is the stable source name used in citations; do not rename files
  without updating the examples that reference them.
- `patient_messages.json` — example patient messages with scenario labels and the
  intent/response type each should produce under the proposed #6 contract. They are
  examples only; no runner executes them.

These files are reusable shared data, unlike the tiny temporary fixtures that unit
tests create in `tmp_path`. See `docs/development/demo-data.md`.
