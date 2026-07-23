import axios, { AxiosError } from "axios";
import { API_BASE_URL, API_HOST } from "../constants.js";

function getApiKey(): string {
  const key = process.env.RAPIDAPI_KEY;
  if (!key) {
    throw new Error(
      "RAPIDAPI_KEY environment variable is required to call the UAE Real Estate API."
    );
  }
  return key;
}

export async function makeApiRequest<T>(
  endpoint: string,
  params?: Record<string, string | number | boolean | undefined>
): Promise<T> {
  const cleanParams: Record<string, string | number | boolean> = {};
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined) {
        cleanParams[key] = value;
      }
    }
  }

  const response = await axios({
    method: "GET",
    url: `${API_BASE_URL}/${endpoint}`,
    params: cleanParams,
    timeout: 30000,
    headers: {
      "x-rapidapi-key": getApiKey(),
      "x-rapidapi-host": API_HOST,
      Accept: "application/json",
    },
  });
  return response.data as T;
}

export function handleApiError(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const axiosError = error as AxiosError;
    if (axiosError.response) {
      switch (axiosError.response.status) {
        case 400:
          return "Error: Invalid request parameters. Please check the values passed (e.g. IDs, ranges) and try again.";
        case 401:
        case 403:
          return "Error: Authentication failed or access denied. Verify the RAPIDAPI_KEY is valid and subscribed to the UAE Real Estate API on RapidAPI.";
        case 404:
          return "Error: Resource not found. Please check the ID or externalID is correct.";
        case 429:
          return "Error: Rate limit exceeded on the RapidAPI subscription. Please wait before making more requests.";
        default:
          return `Error: API request failed with status ${axiosError.response.status}.`;
      }
    } else if (axiosError.code === "ECONNABORTED") {
      return "Error: Request timed out. Please try again.";
    }
    return `Error: Network error while contacting the UAE Real Estate API: ${axiosError.message}`;
  }
  return `Error: Unexpected error occurred: ${error instanceof Error ? error.message : String(error)}`;
}
