import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { makeApiRequest, handleApiError } from "../services/apiClient.js";
import { truncateJson, formatPrice, locationName } from "../services/formatting.js";
import { ResponseFormat } from "../constants.js";
import type {
  PropertiesListResponse,
  PropertyDetail,
  PropertyPhoto,
  PropertySummary,
} from "../types.js";

enum Purpose {
  FOR_SALE = "for-sale",
  FOR_RENT = "for-rent",
}

const SearchPropertiesInputSchema = z
  .object({
    location_external_ids: z
      .string()
      .describe(
        "Comma-separated location externalIDs to search within (e.g. '5002' for Dubai). Use search_locations to find the correct externalID for a city, community, or building."
      ),
    purpose: z
      .nativeEnum(Purpose)
      .default(Purpose.FOR_SALE)
      .describe("Whether to search properties for sale or for rent"),
    category_external_id: z
      .string()
      .optional()
      .describe(
        "Property category externalID, e.g. '4' for apartments, '3' for villas. Use search_locations or category lookups if unsure; omit to search all categories."
      ),
    price_min: z.number().min(0).optional().describe("Minimum price filter"),
    price_max: z.number().min(0).optional().describe("Maximum price filter"),
    rooms_min: z.number().min(0).optional().describe("Minimum number of bedrooms (studio = 0)"),
    rooms_max: z.number().min(0).optional().describe("Maximum number of bedrooms"),
    baths_min: z.number().min(0).optional().describe("Minimum number of bathrooms"),
    area_min: z.number().min(0).optional().describe("Minimum area in square feet"),
    area_max: z.number().min(0).optional().describe("Maximum area in square feet"),
    furnishing_status: z
      .enum(["furnished", "unfurnished", "partly_furnished"])
      .optional()
      .describe("Filter by furnishing status"),
    keywords: z
      .string()
      .optional()
      .describe("Free-text keywords to match in the property title/description, e.g. 'sea view'"),
    sort: z
      .enum(["price-desc", "price-asc", "date-desc", "date-asc", "verified-score"])
      .default("date-desc")
      .describe("Sort order for results"),
    hits_per_page: z.number().int().min(1).max(50).default(10).describe("Results per page (max 50)"),
    page: z.number().int().min(0).default(0).describe("Zero-indexed page number"),
    response_format: z
      .nativeEnum(ResponseFormat)
      .default(ResponseFormat.MARKDOWN)
      .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
  })
  .strict();

type SearchPropertiesInput = z.infer<typeof SearchPropertiesInputSchema>;

function formatPropertySummary(p: PropertySummary): string {
  const lines: string[] = [];
  lines.push(`## ${p.title ?? "Untitled listing"} (${p.externalID ?? p.id ?? "unknown ID"})`);
  lines.push(`- **Price**: ${formatPrice(p.price, p.currency)}${p.rentFrequency ? ` / ${p.rentFrequency}` : ""}`);
  lines.push(`- **Location**: ${locationName(p.location)}`);
  if (p.rooms !== undefined) lines.push(`- **Bedrooms**: ${p.rooms}`);
  if (p.baths !== undefined) lines.push(`- **Bathrooms**: ${p.baths}`);
  if (p.area !== undefined) lines.push(`- **Area**: ${p.area} sqft`);
  if (p.furnishingStatus) lines.push(`- **Furnishing**: ${p.furnishingStatus}`);
  if (p.completionStatus) lines.push(`- **Completion**: ${p.completionStatus}`);
  if (p.agency?.name) lines.push(`- **Agency**: ${p.agency.name}`);
  lines.push("");
  return lines.join("\n");
}

export function registerPropertyTools(server: McpServer): void {
  server.registerTool(
    "uae_real_estate_search_properties",
    {
      title: "Search UAE Properties",
      description: `Search for-sale or for-rent property listings across the UAE (Dubai, Abu Dhabi, Sharjah, etc.) with filters for location, price, rooms, area, and furnishing.

Does NOT create, modify, or contact listings — read-only search only.

Args:
  - location_external_ids (string): Comma-separated location externalIDs. Get these from uae_real_estate_search_locations first if you don't already know them.
  - purpose ('for-sale' | 'for-rent'): default 'for-sale'
  - category_external_id (string, optional): property type filter
  - price_min / price_max (number, optional)
  - rooms_min / rooms_max (number, optional): bedroom count filters
  - baths_min (number, optional)
  - area_min / area_max (number, optional): square feet
  - furnishing_status ('furnished' | 'unfurnished' | 'partly_furnished', optional)
  - keywords (string, optional): free-text search
  - sort ('price-desc' | 'price-asc' | 'date-desc' | 'date-asc' | 'verified-score'): default 'date-desc'
  - hits_per_page (number, 1-50): default 10
  - page (number, zero-indexed): default 0
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  JSON schema:
  {
    "total": number,        // total matching listings (nbHits)
    "page": number,
    "total_pages": number,
    "count": number,        // listings in this response
    "listings": [
      {
        "externalID": string,
        "title": string,
        "price": number,
        "currency": string,
        "purpose": string,
        "location": string,   // full location path, e.g. "Dubai, Downtown Dubai"
        "rooms": number,
        "baths": number,
        "area": number,
        "furnishingStatus": string,
        "agency": string,
        "coverPhotoUrl": string
      }
    ]
  }

Examples:
  - Use when: "Find 2-bedroom apartments for rent in Dubai Marina under 120k AED" -> search_locations first to get Dubai Marina's externalID, then call with purpose='for-rent', rooms_min=2, rooms_max=2, price_max=120000
  - Don't use when: you already have a specific property's externalID and just need its full details (use uae_real_estate_get_property_details instead)

Error Handling:
  - Returns "Error: Invalid request parameters..." if location_external_ids or other filters are malformed
  - Returns "No properties found matching the given filters" if the search returns zero hits`,
      inputSchema: SearchPropertiesInputSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: SearchPropertiesInput) => {
      try {
        const data = await makeApiRequest<PropertiesListResponse>("properties/list", {
          locationExternalIDs: params.location_external_ids,
          purpose: params.purpose,
          categoryExternalID: params.category_external_id,
          priceMin: params.price_min,
          priceMax: params.price_max,
          roomsMin: params.rooms_min,
          roomsMax: params.rooms_max,
          bathsMin: params.baths_min,
          areaMin: params.area_min,
          areaMax: params.area_max,
          furnishingStatus: params.furnishing_status,
          keywords: params.keywords,
          sort: params.sort,
          hitsPerPage: params.hits_per_page,
          page: params.page,
          lang: "en",
        });

        const hits = data.hits ?? [];
        if (hits.length === 0) {
          return {
            content: [{ type: "text", text: "No properties found matching the given filters." }],
          };
        }

        const output = {
          total: data.nbHits ?? hits.length,
          page: data.page ?? params.page,
          total_pages: data.nbPages ?? 1,
          count: hits.length,
          listings: hits.map((p) => ({
            externalID: p.externalID ?? String(p.id ?? ""),
            title: p.title,
            price: p.price,
            currency: p.currency,
            purpose: p.purpose ?? params.purpose,
            location: locationName(p.location),
            rooms: p.rooms,
            baths: p.baths,
            area: p.area,
            furnishingStatus: p.furnishingStatus,
            agency: p.agency?.name,
            coverPhotoUrl: p.coverPhoto?.url,
          })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          const lines = [
            `# Property Search Results`,
            "",
            `Found ${output.total} listings (showing ${output.count}, page ${output.page + 1}/${output.total_pages})`,
            "",
            ...hits.map(formatPropertySummary),
          ];
          text = lines.join("\n");
        } else {
          text = truncateJson(output, output.listings, "listings").text;
        }

        return {
          content: [{ type: "text", text }],
          structuredContent: output,
        };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );

  const PropertyExternalIdSchema = z
    .object({
      external_id: z
        .string()
        .min(1)
        .describe("The property's externalID, obtained from uae_real_estate_search_properties results"),
      response_format: z
        .nativeEnum(ResponseFormat)
        .default(ResponseFormat.MARKDOWN)
        .describe("Output format: 'markdown' for human-readable or 'json' for machine-readable"),
    })
    .strict();

  type PropertyExternalIdInput = z.infer<typeof PropertyExternalIdSchema>;

  server.registerTool(
    "uae_real_estate_get_property_details",
    {
      title: "Get UAE Property Details",
      description: `Fetch full details for a single property listing by its externalID, including description, amenities, agent contact info, and permit number.

Args:
  - external_id (string): the property's externalID from a search result
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  JSON schema:
  {
    "externalID": string,
    "title": string,
    "description": string,
    "price": number,
    "currency": string,
    "purpose": string,
    "location": string,
    "rooms": number,
    "baths": number,
    "area": number,
    "furnishingStatus": string,
    "completionStatus": string,
    "amenities": string[],
    "permitNumber": string,
    "agency": string,
    "contactName": string,
    "phoneNumber": string,
    "photoCount": number
  }

Examples:
  - Use when: "Tell me more about listing ABC123" -> external_id="ABC123"
  - Don't use when: searching for listings by criteria (use uae_real_estate_search_properties instead)

Error Handling:
  - Returns "Error: Resource not found..." if the externalID does not exist`,
      inputSchema: PropertyExternalIdSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: PropertyExternalIdInput) => {
      try {
        const p = await makeApiRequest<PropertyDetail>("properties/detail", {
          externalID: params.external_id,
          lang: "en",
        });

        if (!p || (!p.externalID && !p.id)) {
          return {
            content: [
              { type: "text", text: `Error: No property found with externalID '${params.external_id}'.` },
            ],
          };
        }

        const output = {
          externalID: p.externalID ?? String(p.id ?? ""),
          title: p.title,
          description: p.description,
          price: p.price,
          currency: p.currency,
          purpose: p.purpose,
          location: locationName(p.location),
          rooms: p.rooms,
          baths: p.baths,
          area: p.area,
          furnishingStatus: p.furnishingStatus,
          completionStatus: p.completionStatus,
          amenities: (p.amenities ?? []).map((a) => a.text).filter(Boolean),
          permitNumber: p.permitNumber,
          agency: p.agency?.name,
          contactName: p.contactName,
          phoneNumber: p.phoneNumber?.mobile ?? p.phoneNumber?.phone,
          photoCount: p.photoCount,
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          const lines = [
            `# ${output.title ?? "Untitled listing"} (${output.externalID})`,
            "",
            `**Price**: ${formatPrice(output.price, output.currency)}`,
            `**Location**: ${output.location}`,
            `**Bedrooms**: ${output.rooms ?? "N/A"} | **Bathrooms**: ${output.baths ?? "N/A"} | **Area**: ${output.area ?? "N/A"} sqft`,
            output.furnishingStatus ? `**Furnishing**: ${output.furnishingStatus}` : "",
            output.completionStatus ? `**Completion**: ${output.completionStatus}` : "",
            output.agency ? `**Agency**: ${output.agency}` : "",
            output.contactName ? `**Contact**: ${output.contactName} (${output.phoneNumber ?? "no phone listed"})` : "",
            output.permitNumber ? `**Permit #**: ${output.permitNumber}` : "",
            "",
            output.description ? `## Description\n${output.description}` : "",
            "",
            output.amenities.length ? `## Amenities\n${output.amenities.map((a) => `- ${a}`).join("\n")}` : "",
          ];
          text = lines.filter(Boolean).join("\n");
        } else {
          text = JSON.stringify(output, null, 2);
        }

        return {
          content: [{ type: "text", text }],
          structuredContent: output,
        };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );

  server.registerTool(
    "uae_real_estate_get_similar_properties",
    {
      title: "Get Similar UAE Properties",
      description: `Find properties similar to a given listing (same area/category/price range), useful for comparisons or alternative recommendations.

Args:
  - external_id (string): the reference property's externalID
  - response_format ('markdown' | 'json'): default 'markdown'

Returns: same listing schema as uae_real_estate_search_properties ("listings" array).

Examples:
  - Use when: "Show me other properties like ABC123" -> external_id="ABC123"
  - Don't use when: no reference property exists yet (use uae_real_estate_search_properties instead)

Error Handling:
  - Returns "No similar properties found" if none are returned`,
      inputSchema: PropertyExternalIdSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: PropertyExternalIdInput) => {
      try {
        const data = await makeApiRequest<PropertiesListResponse>(
          "properties/list-similar-properties",
          { externalID: params.external_id, lang: "en" }
        );

        const hits = data.hits ?? [];
        if (hits.length === 0) {
          return {
            content: [{ type: "text", text: "No similar properties found." }],
          };
        }

        const output = {
          count: hits.length,
          listings: hits.map((p) => ({
            externalID: p.externalID ?? String(p.id ?? ""),
            title: p.title,
            price: p.price,
            currency: p.currency,
            location: locationName(p.location),
            rooms: p.rooms,
            baths: p.baths,
            area: p.area,
          })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          text = [`# Properties Similar to ${params.external_id}`, "", ...hits.map(formatPropertySummary)].join(
            "\n"
          );
        } else {
          text = JSON.stringify(output, null, 2);
        }

        return { content: [{ type: "text", text }], structuredContent: output };
      } catch (error) {
        return { content: [{ type: "text", text: handleApiError(error) }] };
      }
    }
  );

  server.registerTool(
    "uae_real_estate_get_property_photos",
    {
      title: "Get UAE Property Photos",
      description: `Fetch the full photo gallery URLs for a property listing.

Args:
  - external_id (string): the property's externalID
  - response_format ('markdown' | 'json'): default 'markdown'

Returns:
  {
    "count": number,
    "photos": [ { "id": number, "url": string, "title": string } ]
  }

Examples:
  - Use when: "Show me all the photos for listing ABC123"

Error Handling:
  - Returns "No photos found for this property" if the gallery is empty`,
      inputSchema: PropertyExternalIdSchema,
      annotations: {
        readOnlyHint: true,
        destructiveHint: false,
        idempotentHint: true,
        openWorldHint: true,
      },
    },
    async (params: PropertyExternalIdInput) => {
      try {
        const data = await makeApiRequest<{ photos?: PropertyPhoto[] } | PropertyPhoto[]>(
          "properties/detail-photos",
          { externalID: params.external_id, lang: "en" }
        );

        const photos = Array.isArray(data) ? data : data.photos ?? [];
        if (photos.length === 0) {
          return { content: [{ type: "text", text: "No photos found for this property." }] };
        }

        const output = {
          count: photos.length,
          photos: photos.map((p) => ({ id: p.id, url: p.url, title: p.title })),
        };

        let text: string;
        if (params.response_format === ResponseFormat.MARKDOWN) {
          text = [
            `# Photos for ${params.external_id}`,
            "",
            `${output.count} photos found`,
            "",
            ...output.photos.map((p, i) => `${i + 1}. ${p.url}`),
          ].join("\n");
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
