import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { makeApiRequest, handleApiError } from "../services/apiClient.js";
import { truncateJson } from "../services/formatting.js";
import { ResponseFormat } from "../constants.js";
import type { AgentListResponse, AgentSummary } from "../types.js";

const ListAgentsInputSchema = z
  .object({
    agency_external_id: z
      .string()
      .optional()
      .describe("Filter agents belonging to a specific agency externalID"),
    location_external_ids: z
      .string()
      .optional()
      .describe("Comma-separated location externalIDs to filter agents operating in that area"),
    name: z.string().optional().describe("Free-text agent name search"),
    hits_per_page: z.number().int().min(1).max(50).default(10).describe("Results per page (max 50)"),
    page: z.number().int().min(0).default(0).describe("Zero-indexed page number"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type ListAgentsInput = z.infer<typeof ListAgentsInputSchema>;

const AgentExternalIdSchema = z
  .object({
    external_id: z.string().min(1).describe("The agent's externalID, from uae_real_estate_list_agents results"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type AgentExternalIdInput = z.infer<typeof AgentExternalIdSchema>;

export function registerAgentTools(server: McpServer): void {
  server.registerTool(
    "uae_real_estate_list_agents",
    {
      title: "List UAE Real Estate Agents",
      description: `Search/list individual real estate agents, optionally filtered by agency, location, or name.

Args:
  - agency_external_id (string, optional): filter by agency externalID
  - location_external_ids (string, optional): comma-separated location externalIDs
  - name (string, optional): free-text agent name filter
  - hits_per_page (number, 1-50): default 10
  - page (number, zero-indexed): default 0
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  {
    "total": number,
    "count": number,
    "agents": [
      { "externalID": string, "name": string, "agency": string, "phone": string, "email": string, "languages": string[] }
    ]
  }

Examples:
  - Use when: "Who are the agents at agency XYZ?" -> agency_external_id="XYZ"
  - Don't use when: looking up agency-level info (use uae_real_estate_list_agencies instead)

Error Handling:
  - Returns "No agents found" if there are no matches`,
      inputSchema: ListAgentsInputSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: ListAgentsInput) => {
      try {
        const data = await makeApiRequest<AgentListResponse>("agents/list", {
          agencyExternalID: params.agency_external_id,
          locationExternalIDs: params.location_external_ids,
          name: params.name,
          hitsPerPage: params.hits_per_page,
          page: params.page,
          lang: "en",
        });

        const hits = data.hits ?? [];
        if (hits.length === 0) {
          return { content: [{ type: "text", text: "No agents found matching the given filters." }] };
        }

        const output = {
          total: data.nbHits ?? hits.length,
          count: hits.length,
          agents: hits.map((a: AgentSummary) => ({
            externalID: a.externalID ?? String(a.id ?? ""),
            name: a.name,
            agency: a.agency?.name,
            phone: a.phoneNumber?.mobile,
            email: a.email,
            languages: a.languages ?? [],
          })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          const lines = [`# UAE Real Estate Agents`, "", `Found ${output.total} agents (showing ${output.count})`, ""];
          for (const a of output.agents) {
            lines.push(`## ${a.name} (${a.externalID})`);
            if (a.agency) lines.push(`- **Agency**: ${a.agency}`);
            if (a.phone) lines.push(`- **Phone**: ${a.phone}`);
            if (a.email) lines.push(`- **Email**: ${a.email}`);
            if (a.languages.length) lines.push(`- **Languages**: ${a.languages.join(", ")}`);
            lines.push("");
          }
          text = lines.join("\n");
        } else {
          text = truncateJson(output, output.agents, "agents").text;
        }

        return { content: [{ type: "text", text }], structuredContent: output };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );

  server.registerTool(
    "uae_real_estate_get_agent_details",
    {
      title: "Get UAE Agent Details",
      description: `Fetch full details for a single real estate agent by their externalID.

Args:
  - external_id (string): the agent's externalID
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  { "externalID": string, "name": string, "agency": string, "phone": string, "email": string, "languages": string[] }

Examples:
  - Use when: "Give me contact info for agent ABC"

Error Handling:
  - Returns "Error: Resource not found..." if the externalID does not exist`,
      inputSchema: AgentExternalIdSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: AgentExternalIdInput) => {
      try {
        const a = await makeApiRequest<AgentSummary>("agents/detail", {
          externalID: params.external_id,
          lang: "en",
        });

        if (!a || (!a.externalID && !a.id)) {
          return {
            content: [{ type: "text", text: `Error: No agent found with externalID '${params.external_id}'.` }],
          };
        }

        const output = {
          externalID: a.externalID ?? String(a.id ?? ""),
          name: a.name,
          agency: a.agency?.name,
          phone: a.phoneNumber?.mobile,
          email: a.email,
          languages: a.languages ?? [],
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          text = [
            `# ${output.name} (${output.externalID})`,
            "",
            output.agency ? `**Agency**: ${output.agency}` : "",
            output.phone ? `**Phone**: ${output.phone}` : "",
            output.email ? `**Email**: ${output.email}` : "",
            output.languages.length ? `**Languages**: ${output.languages.join(", ")}` : "",
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
