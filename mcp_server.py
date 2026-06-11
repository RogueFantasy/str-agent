# Local stdio MCP server for the repo owner's own clients (Claude Code, Claude Desktop).
# TRADEOFF: verify-before-release enforcement for simplicity — these tools trust the
# caller; the booking-bound code-release flow is enforced in agent.py, not here.
# Do not expose this server beyond a trusted local client.
import asyncio
from seed import seed
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent
from knowledge import get_property, format_for_prompt, verify_booking, get_access_codes

server = Server("str-agent")


@server.list_tools()
async def list_tools():
    return [
        Tool(
            name="get_property",
            description="Look up factual details about a specific vacation rental property (check-in/out times, wifi, parking, pet policy, amenities, supply policy).",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Exact property name, e.g. 'Pelican Beach 1006'."}
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="verify_booking",
            description="Verify a guest's booking before releasing sensitive info. Returns 'confirmed', 'outside_window', 'mismatch', 'cancelled', or 'not_found'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "booking_id": {"type": "string"},
                    "guest_last_name": {"type": "string"},
                },
                "required": ["booking_id", "guest_last_name"],
            },
        ),
        Tool(
            name="get_access_codes",
            description="Return door_code and building_code for a property. ONLY call after verify_booking returns 'confirmed'.",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                },
                "required": ["name"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name, arguments):
    if name == "get_property":
        result = format_for_prompt(get_property(arguments["name"]))
    elif name == "verify_booking":
        result, _ = verify_booking(arguments["booking_id"], arguments["guest_last_name"])
    elif name == "get_access_codes":
        codes = get_access_codes(arguments["name"])
        result = str(codes) if codes else "no codes available"
    else:
        result = f"unknown tool: {name}"
    return [TextContent(type="text", text=result)]


async def main():
    seed()  # refresh demo bookings so check-in windows stay relative to today
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
