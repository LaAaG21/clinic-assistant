from fastmcp import FastMCP

mcp = FastMCP("Medical Reports Server")

medical_records: dict[int, list[dict]] = {
    1: [
        {"date": "2026-10-02", "diagnosis": "Flu", "notes": "Rest"},
    ],
    2: [
        {"date": "2026-09-15", "diagnosis": "Back pain", "notes": "Physiotherapy twice a week"},
        {"date": "2026-10-20", "diagnosis": "Follow-up", "notes": "Improving"},
    ],
}

opd_records: dict[int, list[dict]] = {
 1: [
        {"date": "2026-10-02", "department": "General"},
    ],
    2: [
        {"date": "2026-09-15", "department": "Orthopedics"},
        {"date": "2026-10-20", "department": "Orthopedics"},
    ],

}

@mcp.tool
def get_patient_medical_records(patient_id: int) -> list[dict] | dict:
    """ Return the medical records for a given patient ID. """
    if patient_id not in medical_records:
        return {"error": f"Patient {patient_id} does not exist."}
    return medical_records[patient_id]


@mcp.tool
def get_opd_records(patient_id: int) -> list[dict] | dict:
    """ return patient outpatient department records for a given patient ID. 
    """
    if patient_id not in opd_records:
        return {"error": f"Patient {patient_id} does not exist."}
    return opd_records[patient_id]


if __name__ == "__main__":
    mcp.run(transport="http", port=8003)
    
