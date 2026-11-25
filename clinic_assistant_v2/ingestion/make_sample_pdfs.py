"""Regenerate the three made-up clinic PDFs in ingestion/docs/.

Run: uv run python -m ingestion.make_sample_pdfs
"""

from pathlib import Path

from fpdf import FPDF

DOCS_DIR = Path(__file__).parent / "docs"

DOCUMENTS = {
    "doctors.pdf": (
        "Clinic Doctors",
        [
            "Dr. Salma Haddad is a general practitioner. She sees patients on "
            "Sunday, Monday and Wednesday from 09:00 to 15:00.",
            "Dr. Omar Nasser is a cardiologist. He sees patients with heart and "
            "blood pressure problems on Tuesday and Thursday from 10:00 to 16:00.",
            "Dr. Lina Farouk is a dermatologist. She sees skin problems such as "
            "acne, eczema and rashes on Monday and Thursday from 08:00 to 14:00.",
            "Dr. Karim Mansour is a pediatrician. He sees children up to age 14 "
            "on Sunday, Tuesday and Friday from 09:00 to 13:00.",
            "Dr. Huda Rahman is an orthopedic specialist. She sees bone and joint "
            "problems on Wednesday and Saturday from 11:00 to 17:00.",
        ],
    ),
    "facilities.pdf": (
        "Clinic Facilities",
        [
            "The clinic has five departments: General Medicine, Cardiology, "
            "Dermatology, Pediatrics and Orthopedics. General Medicine and "
            "Pediatrics are on the ground floor. The other departments are on "
            "the first floor.",
            "Free parking is available behind the building with 60 spaces. Two "
            "spaces near the entrance are reserved for patients with reduced "
            "mobility. Parking is open from 07:00 to 21:00.",
            "The clinic pharmacy is on the ground floor next to the reception. It "
            "is open Sunday to Thursday from 08:00 to 20:00 and on Friday and "
            "Saturday from 09:00 to 14:00.",
            "A lift and wheelchair ramps connect all floors. The waiting room has "
            "free Wi-Fi and a water dispenser.",
        ],
    ),
    "policies.pdf": (
        "Clinic Policies",
        [
            "Booking: appointments can be booked by phone or through the chat "
            "assistant at least 2 hours before the visit. Each appointment lasts "
            "30 minutes. Please arrive 10 minutes early.",
            "Cancellation: an appointment can be cancelled free of charge up to 24 "
            "hours before the visit. Later cancellations or missed visits may be "
            "charged a fee of 50 AED.",
            "Rescheduling: to change a visit, cancel it and book a new slot. The "
            "same free-cancellation rule applies.",
            "Late arrival: if you arrive more than 15 minutes late, the doctor may "
            "have to rebook your appointment.",
            "Emergencies: the clinic does not handle emergencies. In an emergency "
            "call 998 or go to the nearest hospital.",
        ],
    ),
}


def write_pdf(path: Path, title: str, paragraphs: list[str]) -> None:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, title, new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=11)
    for paragraph in paragraphs:
        pdf.ln(3)
        pdf.multi_cell(0, 6, paragraph)
    pdf.output(str(path))


if __name__ == "__main__":
    for name, (title, paragraphs) in DOCUMENTS.items():
        write_pdf(DOCS_DIR / name, title, paragraphs)
        print(f"wrote {name}")
