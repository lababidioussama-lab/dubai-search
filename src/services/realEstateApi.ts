import { config } from "../config";

export interface PropertySearchParams {
  location?: string;
  purpose?: string;
  propertyType?: string;
  minPrice?: string;
  maxPrice?: string;
  bedrooms?: string;
  page?: string;
}

export class RealEstateApiError extends Error {
  constructor(message: string, public readonly status: number) {
    super(message);
    this.name = "RealEstateApiError";
  }
}

export async function searchProperties(params: PropertySearchParams): Promise<unknown> {
  const { rapidApi } = config;
  const url = new URL(`https://${rapidApi.host}${rapidApi.searchPath}`);

  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      url.searchParams.set(key, value);
    }
  }

  const response = await fetch(url, {
    headers: {
      "x-rapidapi-key": rapidApi.key,
      "x-rapidapi-host": rapidApi.host,
    },
  });

  if (!response.ok) {
    const body = await response.text();
    throw new RealEstateApiError(
      `Upstream request failed (${response.status}): ${body}`,
      response.status
    );
  }

  return response.json();
}
