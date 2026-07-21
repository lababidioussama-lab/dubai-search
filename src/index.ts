import express from "express";
import { config } from "./config";
import { propertiesRouter } from "./routes/properties";

const app = express();

app.get("/health", (_req, res) => {
  res.json({ status: "ok" });
});

app.use("/api/properties", propertiesRouter);

app.listen(config.port, () => {
  console.log(`dubai-search API listening on port ${config.port}`);
});
