import { Router } from "express";
import { RealEstateApiError, searchProperties } from "../services/realEstateApi";

export const propertiesRouter = Router();

propertiesRouter.get("/search", async (req, res) => {
  const { location, purpose, propertyType, minPrice, maxPrice, bedrooms, page } = req.query;

  try {
    const results = await searchProperties({
      location: typeof location === "string" ? location : undefined,
      purpose: typeof purpose === "string" ? purpose : undefined,
      propertyType: typeof propertyType === "string" ? propertyType : undefined,
      minPrice: typeof minPrice === "string" ? minPrice : undefined,
      maxPrice: typeof maxPrice === "string" ? maxPrice : undefined,
      bedrooms: typeof bedrooms === "string" ? bedrooms : undefined,
      page: typeof page === "string" ? page : undefined,
    });

    res.json(results);
  } catch (error) {
    if (error instanceof RealEstateApiError) {
      res.status(502).json({ error: error.message });
      return;
    }

    if (error instanceof Error && error.message.startsWith("Missing required environment variable")) {
      res.status(500).json({ error: "Server is not configured with RapidAPI credentials" });
      return;
    }

    res.status(500).json({ error: "Unexpected error while searching properties" });
  }
});
