"""Fixed, evidence-gated replies for the fixture questions; no API or inference."""

from typing import TypedDict


class Evidence(TypedDict):
    passage_id: str
    source_id: str
    text: str


FALLBACK = "I do not know from the clinic documents"
# Question -> (required source, required evidence substring, fixed reply).
# This demonstrates the interface, not a general-purpose support verifier.
REPLIES = {
    "When does the clinic open?": (
        "clinic-hours.md",
        "opens Monday to Friday from 09:00 to 17:00",
        "The clinic opens Monday to Friday from 09:00 to 17:00.",
    ),
    "How do I book appointments?": (
        "appointments.md",
        "Book appointments by calling reception on 555-0100",
        "Book appointments by calling reception on 555-0100.",
    ),
    "Is parking free?": (
        "access.md",
        "Free parking is available behind the clinic",
        "Yes. Free parking is available behind the clinic.",
    ),
    "Do cancellations require approval?": (
        "appointments.md",
        "Appointment cancellations require staff approval",
        "Yes. Appointment cancellations require staff approval.",
    ),
    "Which insurance does the clinic accept?": (
        "billing.md",
        "The clinic accepts Cedar insurance",
        "The clinic accepts Cedar insurance.",
    ),
    "Where can I leave my car?": (
        "access.md",
        "Free parking is available behind the clinic",
        "Free parking is available behind the clinic.",
    ),
    "How much does parking cost?": (
        "access.md",
        "Free parking is available behind the clinic",
        "Parking is free.",
    ),
    "Is the clinic open on Sunday?": (
        "clinic-hours.md",
        "It is closed on Saturday and Sunday",
        "No. The clinic is closed on Saturday and Sunday.",
    ),
}


def fake_answer(question: str, evidence: list[Evidence]) -> str:
    """Answer only a fixed question with its supporting retrieved source/text."""
    reply = REPLIES.get(question)
    if reply is not None:
        source, required_text, answer = reply
        for passage in evidence:
            if passage["source_id"] == source and required_text in passage["text"]:
                return f"{answer} Source: {passage['source_id']}"
    return FALLBACK
