# dubai-search

A static Dubai property search page built on the **UAE Real Estate API3** (RapidAPI).

## Usage
1. Subscribe to the API on RapidAPI and copy your `X-RapidAPI-Key`.
2. Serve the folder: `npx serve .` or `python3 -m http.server 8000`, then open it in a browser.
3. Paste the key (it stays in your browser's localStorage), choose filters, and search.

## Configuring endpoints
`config.js` holds the API host, the endpoint paths and the query-parameter names.
Check them against the endpoints listed in the RapidAPI playground and edit `config.js` if they differ.
No other file needs to change. The "Raw API response" panel shows exactly what the API returned.

> Note: the key is sent from the browser, so this setup is meant for personal or local use.
> For a public deployment, put the API calls behind a server that keeps the key private.
