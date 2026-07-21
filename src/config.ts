function requireEnv(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`Missing required environment variable: ${name}`);
  }
  return value;
}

export const config = {
  port: Number(process.env.PORT) || 3000,
  rapidApi: {
    get key(): string {
      return requireEnv("RAPIDAPI_KEY");
    },
    host: process.env.RAPIDAPI_HOST || "uae-real-estate-data-api-2.p.rapidapi.com",
    searchPath: process.env.RAPIDAPI_SEARCH_PATH || "/properties/search",
  },
};
