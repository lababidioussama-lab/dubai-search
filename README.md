# UAE Real Estate MCP Server

An MCP (Model Context Protocol) server that wraps the [UAE Real Estate](https://rapidapi.com) RapidAPI (`uae-real-estate2.p.rapidapi.com`), exposing property search, listing details, locations, agencies, and agents as MCP tools.

## Tools

| Tool | Description |
| --- | --- |
| `uae_real_estate_search_properties` | Search for-sale/for-rent listings by location, price, rooms, area, furnishing |
| `uae_real_estate_get_property_details` | Full details for a single listing (description, amenities, contact info) |
| `uae_real_estate_get_similar_properties` | Listings similar to a given property |
| `uae_real_estate_get_property_photos` | Photo gallery for a listing |
| `uae_real_estate_search_locations` | Auto-complete search to resolve a location's externalID |
| `uae_real_estate_list_agencies` | Search/list real estate agencies |
| `uae_real_estate_get_agency_details` | Full details for a single agency |
| `uae_real_estate_list_agents` | Search/list individual agents |
| `uae_real_estate_get_agent_details` | Full details for a single agent |

## Setup

```bash
npm install
npm run build
```

Set your RapidAPI key (subscribed to the UAE Real Estate API):

```bash
export RAPIDAPI_KEY=your-rapidapi-key-here
```

Run the server (stdio transport):

```bash
npm start
```

## Using with Claude Desktop (local server)

1. Build the server first (`npm install && npm run build`) so `dist/index.js` exists.
2. Open Claude Desktop's config file:
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

   (In Claude Desktop: Settings → Developer → Edit Config)
3. Add this server under `mcpServers`, using an **absolute path** to `dist/index.js`:

```json
{
  "mcpServers": {
    "uae-real-estate": {
      "command": "node",
      "args": ["/absolute/path/to/dubai-search/dist/index.js"],
      "env": {
        "RAPIDAPI_KEY": "your-rapidapi-key-here"
      }
    }
  }
}
```

4. Fully quit and restart Claude Desktop.
5. Click the "Add files, connectors, and more" icon in the input box → Connectors → Manage connectors → **uae-real-estate** to confirm the 9 tools are listed.

If it doesn't connect, check the server runs standalone first (`RAPIDAPI_KEY=... node dist/index.js`), then check logs:
- **macOS**: `tail -n 20 -f ~/Library/Logs/Claude/mcp*.log`
- **Windows**: `%APPDATA%\Claude\logs\mcp*.log`

This is the same pattern used for the [official filesystem MCP server](https://modelcontextprotocol.io/docs/develop/connect-local-servers) — a local server run via `command`/`args`, distinct from remote gateway configs like RapidAPI's hosted `mcp.rapidapi.com` proxy.

## Development

```bash
npm run dev    # watch mode
npm run build  # compile TypeScript to dist/
```
