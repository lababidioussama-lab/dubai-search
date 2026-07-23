#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { registerPropertyTools } from "./tools/properties.js";
import { registerLocationTools } from "./tools/locations.js";
import { registerAgencyTools } from "./tools/agencies.js";
import { registerAgentTools } from "./tools/agents.js";

const server = new McpServer({
  name: "uae-real-estate-mcp-server",
  version: "1.0.0",
});

registerPropertyTools(server);
registerLocationTools(server);
registerAgencyTools(server);
registerAgentTools(server);

async function main(): Promise<void> {
  if (!process.env.RAPIDAPI_KEY) {
    console.error(
      "ERROR: RAPIDAPI_KEY environment variable is required (your RapidAPI key subscribed to the UAE Real Estate API)."
    );
    process.exit(1);
  }

  const transport = new StdioServerTransport();
  await server.connect(transport);
  console.error("UAE Real Estate MCP server running via stdio");
}

main().catch((error) => {
  console.error("Server error:", error);
  process.exit(1);
});
