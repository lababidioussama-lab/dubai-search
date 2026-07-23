import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { makeApiRequest, handleApiError } from "../services/apiClient.js";
import { ResponseFormat } from "../constants.js";
import type { LocationSuggestion } from "../types.js";

const SearchLocationsInputSchema = z
  .object({
    query: z
      .string()
      .min(2, "Query must be at least 2 characters")
      .max(200)
      .describe("Free-text location name to search for, e.g. 'Dubai Marina', 'Downtown Dubai', 'Business Bay'"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type SearchLocationsInput = z.infer<typeof SearchLocationsInputSchema>;

export function registerLocationTools(server: McpServer): void {
  server.registerTool(
    "uae_real_estate_search_locations",
    {
      title: "Search UAE Locations",
      description: `Auto-complete search for UAE locations (cities, communities, buildings) to find the location externalID needed by uae_real_estate_search_properties.

Args:
  - query (string, min 2 chars): location name to search, e.g. "Dubai Marina"
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  {
    "count": number,
    "locations": [
      { "externalID": string, "name": string, "type": string, "listingCount": number }
    ]
  }

Examples:
  - Use when: "Find apartments in JBR" -> first call with query="JBR" to resolve its externalID, then pass that externalID into uae_real_estate_search_properties
  - Don't use when: you already know the location externalID

Error Handling:
  - Returns "No locations found matching '<query>'" if there are no matches`,
      inputSchema: SearchLocationsInputSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: SearchLocationsInput) => {
      try {
        const data = await makeApiRequest<{ hits?: LocationSuggestion[] } | LocationSuggestion[]>(
          "auto-complete",
          { query: params.query, lang: "en" }
        );

        const hits = Array.isArray(data) ? data : data.hits ?? [];
        if (hits.length === 0) {
          return {
            content: [{ type: "text", text: `No locations found matching '${params.query}'.` }],
          };
        }

        const output = {
          count: hits.length,
          locations: hits.map((h) => ({
            externalID: h.externalID ?? String(h.id ?? ""),
            name: h.name,
            type: h.type,
            listingCount: h.hitsCount,
          })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          const lines = [`# Location Matches for '${params.query}'`, ""];
          for (const loc of output.locations) {
            lines.push(
              `- **${loc.name}** (externalID: ${loc.externalID}, type: ${loc.type ?? "unknown"}${
                loc.listingCount !== undefined ? `, ${loc.listingCount} listings` : ""
              })`
            );
          }
          text = lines.join("\n");
        } else {
          text = JSON.stringify(output, null, 2);
        }

        return { content: [{ type: "text", text }], structuredContent: output };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );
}
