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

## Using with an MCP client

Add to your client's MCP server config, e.g.:

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

## Development

```bash
npm run dev    # watch mode
npm run build  # compile TypeScript to dist/
```
