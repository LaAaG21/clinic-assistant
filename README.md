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

## Research

- [Clinic-document retrieval comparison](docs/research/clinic-document-retrieval.md)
- [Proposed retrieval ADR](docs/adr/0001-clinic-document-retrieval.md)
