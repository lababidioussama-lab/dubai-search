// GET /api/file?u=<direct file url>&name=<filename>&k=<api key>
// Relays a file so the browser can save it (or convert it to MP3) instead of just opening it.
// The key is a query parameter because plain download links can't send headers.
import type { Config } from "@netlify/functions"

const MAX_BYTES = 20 * 1024 * 1024 // Netlify's limit for a streamed response

export default async (req: Request) => {
  const q = new URL(req.url).searchParams
  const key = Netlify.env.get("API_KEY")
  if (key && q.get("k") !== key) return new Response("Access key missing or wrong", { status: 401 })

  const target = q.get("u") ?? ""
  if (!/^https?:\/\//.test(target)) return new Response("Missing file link", { status: 400 })

  const upstream = await fetch(target, {
    redirect: "follow",
    headers: { referer: new URL(target).origin + "/", "user-agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1" },
  }).catch(() => null)
  if (!upstream?.ok || !upstream.body) {
    return new Response(`Could not fetch the file (${upstream?.status ?? "no response"})`, { status: 502 })
  }

  const size = Number(upstream.headers.get("content-length") ?? 0)
  if (size > MAX_BYTES) return new Response("File too large to relay", { status: 413 })

  const name = (q.get("name") ?? "download").replace(/[^\w.\- ]+/g, "_").slice(0, 120)
  return new Response(upstream.body, {
    headers: {
      "content-type": upstream.headers.get("content-type") ?? "application/octet-stream",
      ...(size ? { "content-length": String(size) } : {}),
      "content-disposition": `${q.get("inline") ? "inline" : "attachment"}; filename="${name}"`,
      "cache-control": "private, max-age=600",
    },
  })
}

export const config: Config = { path: "/api/file", method: "GET" }
