import { CHARACTER_LIMIT } from "../constants.js";

/** Serializes structured data to JSON, truncating the `items` array if the result would exceed CHARACTER_LIMIT. */
export function truncateJson(
  response: Record<string, unknown>,
  items: unknown[],
  itemsKey: string
): { text: string; truncated: boolean } {
  let text = JSON.stringify(response, null, 2);
  if (text.length <= CHARACTER_LIMIT || items.length <= 1) {
    return { text, truncated: false };
  }

  const truncatedItems = items.slice(0, Math.max(1, Math.floor(items.length / 2)));
  const truncatedResponse = {
    ...response,
    [itemsKey]: truncatedItems,
    truncated: true,
    truncation_message: `Response truncated from ${items.length} to ${truncatedItems.length} items. Narrow your filters or use pagination to see more results.`,
  };
  text = JSON.stringify(truncatedResponse, null, 2);
  return { text, truncated: true };
}

export function formatPrice(price?: number, currency?: string): string {
  if (price === undefined || price === null) return "Price on request";
  const formatted = price.toLocaleString("en-US");
  return currency ? `${formatted} ${currency}` : formatted;
}

export function locationName(
  location?: Array<{ name?: string; level?: number }>
): string {
  if (!location || location.length === 0) return "Unknown location";
  return location.map((l) => l.name).filter(Boolean).join(", ");
}
