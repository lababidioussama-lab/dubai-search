# dubai-search

A small Express/TypeScript API that searches UAE real estate listings by
proxying the [RapidAPI UAE Real Estate Data API](https://rapidapi.com/).

## Setup

```bash
npm install
cp .env.example .env
# edit .env and set RAPIDAPI_KEY to your own key
```

## Development

```bash
npm run dev
```

## Build & run

```bash
npm run build
npm start
```

## Endpoints

- `GET /health` — liveness check
- `GET /api/properties/search` — search properties. Supported query params:
  `location`, `purpose`, `propertyType`, `minPrice`, `maxPrice`, `bedrooms`, `page`

`RAPIDAPI_SEARCH_PATH` (see `.env.example`) controls which upstream path is
called — adjust it to match the exact endpoint documented for your RapidAPI
subscription.
