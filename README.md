# Clinic Front-Desk Assistant

A team project to build an AI-powered REST API for a clinic's front desk.

## Planned Features

- Answer clinic questions using clinic documents and cite the sources.
- Find available appointments and book them without double booking.
- Require staff approval for cancellations and same-day bookings.
- Preserve conversations and pending approvals after a restart.
- Respond immediately to emergency messages and flag them for staff.

The assistant must not provide diagnoses or treatment recommendations.

## Tech Stack

Python, FastAPI, LangGraph, OpenAI SDK, PostgreSQL, psycopg, and Docker Compose.

Database access uses plain SQL without an ORM.

## Status

In development.

## Standalone experiments

- [Issue #4: staff approval interrupt/resume](experiments/staff_approval/README.md)
- [Research note and proposed recommendation](docs/research/004-staff-interrupt-resume.md)
