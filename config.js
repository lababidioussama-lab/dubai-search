// RapidAPI settings for "UAE Real Estate API3".
// The endpoint paths below are best guesses — check them against the
// RapidAPI playground and edit here if they differ.
window.API_CONFIG = {
  host: "uae-real-estate-api3.p.rapidapi.com",
  endpoints: {
    // Location autocomplete: returns locations matching `query`.
    autocomplete: { path: "/autocomplete", queryParam: "query" },
    // Property search. Keys are form fields, values are the API's param names.
    search: {
      path: "/properties_search",
      params: {
        purpose: "purpose",        // "for-sale" | "for-rent"
        location: "location_ids",  // id(s) from autocomplete
        category: "category",      // e.g. "apartments", "villas"
        minPrice: "price_min",
        maxPrice: "price_max",
        beds: "rooms",
        page: "page",
      },
    },
  },
};
