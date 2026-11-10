from fastmcp import FastMCP

mcp = FastMCP("Pharmacy Server")

inventory: dict[str, int] = {
    "Paracetamol": 120,
    "Ibuprofen": 40,
}


@mcp.tool
def view_inventory() -> dict[str, int]:
    """Return the full pharmacy inventory of medicines."""
    return inventory


@mcp.tool
def add_inventory(medicine: str, quantity: int) -> dict:
    """Add medicine to the pharmacy inventory."""
    if quantity <= 0:
        return {"error": f"Quantity must be greater than zero, got {quantity}."}
    inventory[medicine] = inventory.get(medicine, 0) + quantity
    return {"medicine": medicine, "stock": inventory[medicine]}


if __name__ == "__main__":
    mcp.run(transport="http", port=8002)
