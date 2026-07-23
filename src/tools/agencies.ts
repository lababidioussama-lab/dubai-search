import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { makeApiRequest, handleApiError } from "../services/apiClient.js";
import { truncateJson } from "../services/formatting.js";
import { ResponseFormat } from "../constants.js";
import type { AgencyListResponse, AgencySummary } from "../types.js";

const ListAgenciesInputSchema = z
  .object({
    location_external_ids: z
      .string()
      .optional()
      .describe("Comma-separated location externalIDs to filter agencies operating in that area"),
    name: z.string().optional().describe("Free-text agency name search"),
    hits_per_page: z.number().int().min(1).max(50).default(10).describe("Results per page (max 50)"),
    page: z.number().int().min(0).default(0).describe("Zero-indexed page number"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type ListAgenciesInput = z.infer<typeof ListAgenciesInputSchema>;

const AgencyExternalIdSchema = z
  .object({
    external_id: z.string().min(1).describe("The agency's externalID, from uae_real_estate_list_agencies results"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type AgencyExternalIdInput = z.infer<typeof AgencyExternalIdSchema>;

export function registerAgencyTools(server: McpServer): void {
  server.registerTool(
    "uae_real_estate_list_agencies",
    {
      title: "List UAE Real Estate Agencies",
      description: `Search/list real estate agencies operating in the UAE, optionally filtered by location or name.

Args:
  - location_external_ids (string, optional): comma-separated location externalIDs
  - name (string, optional): free-text agency name filter
  - hits_per_page (number, 1-50): default 10
  - page (number, zero-indexed): default 0
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  {
    "total": number,
    "count": number,
    "agencies": [
      { "externalID": string, "name": string, "licenseNumber": string, "verified": boolean, "tier": string }
    ]
  }

Examples:
  - Use when: "What agencies operate in Dubai Marina?" -> location_external_ids resolved via uae_real_estate_search_locations
  - Don't use when: looking up an individual agent (use uae_real_estate_list_agents instead)

Error Handling:
  - Returns "No agencies found" if there are no matches`,
      inputSchema: ListAgenciesInputSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: ListAgenciesInput) => {
      try {
        const data = await makeApiRequest<AgencyListResponse>("agencies/list", {
          locationExternalIDs: params.location_external_ids,
          name: params.name,
          hitsPerPage: params.hits_per_page,
          page: params.page,
          lang: "en",
        });

        const hits = data.hits ?? [];
        if (hits.length === 0) {
          return { content: [{ type: "text", text: "No agencies found matching the given filters." }] };
        }

        const output = {
          total: data.nbHits ?? hits.length,
          count: hits.length,
          agencies: hits.map((a: AgencySummary) => ({
            externalID: a.externalID ?? String(a.id ?? ""),
            name: a.name,
            licenseNumber: a.licenseNumber,
            verified: a.verification?.verified ?? false,
            tier: a.productLabel?.tier,
          })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          const lines = [`# UAE Real Estate Agencies`, "", `Found ${output.total} agencies (showing ${output.count})`, ""];
          for (const a of output.agencies) {
            lines.push(`## ${a.name} (${a.externalID})`);
            if (a.licenseNumber) lines.push(`- **License #**: ${a.licenseNumber}`);
            lines.push(`- **Verified**: ${a.verified ? "Yes" : "No"}`);
            if (a.tier) lines.push(`- **Tier**: ${a.tier}`);
            lines.push("");
          }
          text = lines.join("\n");
        } else {
          text = truncateJson(output, output.agencies, "agencies").text;
        }

        return { content: [{ type: "text", text }], structuredContent: output };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );

  server.registerTool(
    "uae_real_estate_get_agency_details",
    {
      title: "Get UAE Agency Details",
      description: `Fetch full details for a single real estate agency by its externalID.

Args:
  - external_id (string): the agency's externalID
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  { "externalID": string, "name": string, "licenseNumber": string, "verified": boolean, "logoUrl": string }

Examples:
  - Use when: "Tell me about agency XYZ" -> external_id="XYZ"

Error Handling:
  - Returns "Error: Resource not found..." if the externalID does not exist`,
      inputSchema: AgencyExternalIdSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: AgencyExternalIdInput) => {
      try {
        const a = await makeApiRequest<AgencySummary>("agencies/detail", {
          externalID: params.external_id,
          lang: "en",
        });

        if (!a || (!a.externalID && !a.id)) {
          return {
            content: [{ type: "text", text: `Error: No agency found with externalID '${params.external_id}'.` }],
          };
        }

        const output = {
          externalID: a.externalID ?? String(a.id ?? ""),
          name: a.name,
          licenseNumber: a.licenseNumber,
          verified: a.verification?.verified ?? false,
          logoUrl: a.logo?.url,
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          text = [
            `# ${output.name} (${output.externalID})`,
            "",
            output.licenseNumber ? `**License #**: ${output.licenseNumber}` : "",
            `**Verified**: ${output.verified ? "Yes" : "No"}`,
          ]
            .filter(Boolean)
            .join("\n");
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
