import asyncio

from fastmcp import Client

SERVERS = {
    "booking": "http://127.0.0.1:8001/mcp",
    "pharmacy": "http://127.0.0.1:8002/mcp",
    "reports": "http://127.0.0.1:8003/mcp",
}


async def call_and_print(
    client: Client, server: str, tool: str, arguments: dict
) -> None:
    """Call one tool and print the result as <server>.<tool> -> <result>."""
    result = await client.call_tool(tool, arguments)
    print(f"{server}.{tool} -> {result.data}")


async def run_booking() -> None:
    """List the Booking tools and call each one, including two error cases."""
    async with Client(SERVERS["booking"]) as client:
        tools = await client.list_tools()
        print("booking tools:", [tool.name for tool in tools])

        await call_and_print(
            client,
            "booking",
            "register_patient",
            {"name": "Salim", "phone": "99112233"},
        )
        appointment = {
            "patient_id": 1,
            "doctor": "Dr. Huda",
            "date": "2026-11-20",
            "time": "10:00",
        }
        await call_and_print(client, "booking", "book_appointment", appointment)
        await call_and_print(client, "booking", "book_appointment", appointment)
        unknown_patient = {
            "patient_id": 99,
            "doctor": "Dr. Huda",
            "date": "2026-11-21",
            "time": "09:00",
        }
        await call_and_print(client, "booking", "book_appointment", unknown_patient)


async def run_pharmacy() -> None:
    """List the Pharmacy tools, show an error case, then add a new medicine."""
    async with Client(SERVERS["pharmacy"]) as client:
        tools = await client.list_tools()
        print("pharmacy tools:", [tool.name for tool in tools])

        await call_and_print(client, "pharmacy", "view_inventory", {})
        await call_and_print(
            client,
            "pharmacy",
            "add_inventory",
            {"medicine": "Ibuprofen", "quantity": 0},
        )
        await call_and_print(
            client,
            "pharmacy",
            "add_inventory",
            {"medicine": "Amoxicillin", "quantity": 30},
        )
        await call_and_print(client, "pharmacy", "view_inventory", {})


async def run_reports() -> None:
    """List the Medical Reports tools and call each one, including an error case."""
    async with Client(SERVERS["reports"]) as client:
        tools = await client.list_tools()
        print("reports tools:", [tool.name for tool in tools])

        await call_and_print(
            client, "reports", "get_patient_medical_records", {"patient_id": 1}
        )
        await call_and_print(client, "reports", "get_opd_records", {"patient_id": 1})
        await call_and_print(
            client, "reports", "get_patient_medical_records", {"patient_id": 99}
        )


async def main() -> None:
    """Run Booking and Reports together, then finish with the pharmacy flow."""
    await asyncio.gather(run_booking(), run_reports())
    await run_pharmacy()


if __name__ == "__main__":
    asyncio.run(main())
