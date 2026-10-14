// POST /api {"url": "<post link>", "mode": "video" | "audio", "quality": "max" | "1080" | "720" | "480" | "360"}
// -> cobalt-style JSON:
//   {status: "redirect", type, url, filename, title, thumbnail}   one file
//   {status: "picker", title, picker: [{type, url, thumb}]}       carousel / slideshow
//   {status: "error", error: {code}}
// type is "video", "audio" or "photo".
// GET /api?redirect=1&mode=video&url=<post link> answers with a redirect to the file itself,
// so an iOS Shortcut can do: Get Contents of URL -> Save to Photo Album. The link goes last
// and may stay unencoded (its own ?/& are kept).
// If the API_KEY env var is set, requests need the header "Authorization: Api-Key <key>".
import type { Config } from "@netlify/functions"
import { execFile } from "node:child_process"
import { chmodSync, copyFileSync, existsSync } from "node:fs"
import { join } from "node:path"

type Mode = "video" | "audio"
type Options = { mode: Mode; quality: string }

const BIN = "/tmp/yt-dlp"
const IMAGE_EXT = /^(jpe?g|png|webp|gif|heic)$/i

// One file over plain https (no merging available here), mp4/m4a when possible —
// what Photos and browsers can save directly.
function formatFor({ mode, quality }: Options): string {
  if (mode === "audio") return "ba[ext=m4a][protocol^=http]/ba[protocol^=http]/b[protocol^=http]/b"
  const h = /^\d+$/.test(quality) ? `[height<=${quality}]` : ""
  return [`b${h}[ext=mp4][protocol^=http]`, `b${h}[protocol^=http]`, "b[ext=mp4][protocol^=http]", "b[protocol^=http]", "b"].join("/")
}

function ytDlpPath(): string {
  if (!existsSync(BIN)) {
    const roots = [process.env.LAMBDA_TASK_ROOT, process.cwd()].filter(Boolean) as string[]
    const src = roots.map((r) => join(r, "bin/yt-dlp")).find(existsSync)
    if (!src) throw new Error("yt-dlp binary missing from the deploy")
    copyFileSync(src, BIN)
    chmodSync(BIN, 0o755)
  }
  return BIN
}

function runYtDlp(url: string, opts: Options): Promise<any> {
  const args = ["-J", "-f", formatFor(opts), "--no-warnings", "--no-cache-dir", "--playlist-end", "20", url]
  return new Promise((resolve, reject) => {
    execFile(ytDlpPath(), args, {
      timeout: 50_000,
      maxBuffer: 64 * 1024 * 1024,
      env: { ...process.env, HOME: "/tmp", TMPDIR: "/tmp" },
    }, (err, stdout, stderr) => {
      if (err) return reject(new Error((stderr || err.message).trim().split("\n").pop()))
      try { resolve(JSON.parse(stdout)) } catch { reject(new Error("unreadable yt-dlp output")) }
    })
  })
}

function typeOf(e: any, mode: Mode): string {
  if (IMAGE_EXT.test(e.ext ?? "")) return "photo"
  if (mode === "audio" || e.vcodec === "none") return "audio"
  return "video"
}

const TIKWM = "https://www.tikwm.com"

// TikTok via tikwm: no-watermark links that download without cookies.
async function tiktok(url: string, { mode, quality }: Options): Promise<object> {
  const res = await fetch(`${TIKWM}/api/`, {
    method: "POST",
    headers: { "content-type": "application/x-www-form-urlencoded" },
    body: new URLSearchParams({ url, hd: "1" }),
  })
  const { code, msg, data } = await res.json()
  if (code !== 0 || !data) throw new Error(msg || "TikTok lookup failed")
  const abs = (u: string) => (u?.startsWith("/") ? TIKWM + u : u)
  const base = { title: data.title, thumbnail: abs(data.cover) }
  if (mode === "audio" && data.music) {
    return { status: "redirect", type: "audio", url: abs(data.music), filename: `${data.id}.mp3`, ...base }
  }
  if (data.images?.length) {
    return { status: "picker", title: data.title, picker: data.images.map((u: string) => ({ type: "photo", url: u, thumb: u })) }
  }
  const hd = quality === "max" || Number(quality) >= 1080
  return { status: "redirect", type: "video", url: abs((hd && data.hdplay) || data.play), filename: `${data.id}.mp4`, ...base }
}

// Instagram blocks most server downloads, but its public embed page still lists the
// full-size photos (display_url) and video files (video_url) of a post or carousel.
const BROWSER_UA = "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1"

export async function instagram(url: string, { mode }: Options): Promise<object | null> {
  const code = url.match(/instagram\.com\/(?:[\w.]+\/)?(?:p|reel|reels|tv)\/([\w-]+)/)?.[1]
  if (!code) return null
  const res = await fetch(`https://www.instagram.com/p/${code}/embed/captioned/`, { headers: { "user-agent": BROWSER_UA } })
  if (!res.ok) return null
  const html = await res.text()
  // The post data sits in JSON inside a JS string, so quotes and slashes may be escaped
  // once or twice (\" \/ \\u0026). Match up to the next quote, then strip the escaping.
  const clean = (v: string) => v.replace(/\\+\//g, "/").replace(/\\+u0026/g, "&").replace(/\\+/g, "")
  const grab = (key: string) => [...new Set(
    [...html.matchAll(new RegExp(`${key}\\\\*"\\s*:\\s*\\\\*"(https:[^"]*?)\\\\*"`, "g"))].map((m) => clean(m[1])),
  )]
  const videos = grab("video_url")
  let photos = grab("display_url")
  if (!photos.length) {
    // Single photo without JSON: take the largest size from the image's srcset.
    const srcset = html.match(/class="EmbeddedMediaImage"[^>]*srcset="([^"]+)"/)?.[1]
    const best = srcset?.split(",").map((c) => c.trim().split(/\s+/))
      .sort((a, b) => parseInt(b[1]) - parseInt(a[1]))[0]?.[0]
    if (best) photos = [best.replace(/&amp;/g, "&")]
  }
  const title = html.match(/class="CaptionUsername"[^>]*>([^<]+)/)?.[1]?.trim() ?? "instagram"
  const items = videos.length && mode === "video"
    ? videos.map((u) => ({ type: "video", url: u, thumb: photos[0] }))
    : videos.length ? videos.map((u) => ({ type: "audio", url: u, thumb: photos[0] }))
    : photos.map((u) => ({ type: "photo", url: u, thumb: u }))
  if (!items.length) return null
  if (items.length === 1) {
    const [it] = items
    return { status: "redirect", type: it.type, url: it.url, filename: `${code}.${it.type === "photo" ? "jpg" : "mp4"}`, title, thumbnail: it.thumb }
  }
  return { status: "picker", title, picker: items }
}

async function expand(url: string): Promise<string> {
  const res = await fetch(url, { headers: { "user-agent": BROWSER_UA } }).catch(() => null)
  return res?.url && /tiktok\.com/.test(res.url) ? res.url : url
}

// Photo-only posts: yt-dlp only handles video, so fall back to the page's preview image.
async function pageImage(url: string): Promise<object | null> {
  const res = await fetch(url, { headers: { "user-agent": "Mozilla/5.0 (compatible; facebookexternalhit/1.1)" } })
  const html = await res.text()
  const meta = (p: string) => html.match(new RegExp(`<meta[^>]+(?:property|name)=["']${p}["'][^>]+content=["']([^"']+)`, "i"))?.[1]
  const img = meta("og:image") ?? meta("twitter:image")
  if (!img) return null
  const src = img.replace(/&amp;/g, "&")
  return { status: "redirect", type: "photo", url: src, filename: "image.jpg", title: meta("og:title"), thumbnail: src }
}

const reply = (body: object, status = 200) => Response.json(body, { status })
const fail = (code: string, status = 400) => reply({ status: "error", error: { code } }, status)

export default async (req: Request) => {
  const key = Netlify.env.get("API_KEY")
  if (key && req.headers.get("authorization") !== `Api-Key ${key}`) return fail("auth.key.invalid", 401)

  const q = new URL(req.url).searchParams
  const body = req.method === "POST" ? await req.json().catch(() => ({})) : {}
  const rawLink = req.url.split(/[?&]url=/)[1]
  const url: string | null = body.url ?? (rawLink ? decodeURIComponent(rawLink).trim() : null)
  const redirect = q.has("redirect")
  const opts: Options = {
    mode: (body.mode ?? q.get("mode")) === "audio" ? "audio" : "video",
    quality: String(body.quality ?? body.videoQuality ?? q.get("quality") ?? "max"),
  }
  if (!url || !/^https?:\/\//.test(url)) return fail("link.missing")

  try {
    const result: any = await resolve(url, opts)
    if (redirect && result.status !== "error") {
      const target = result.status === "picker" ? result.picker[0]?.url : result.url
      if (target) return Response.redirect(target, 302)
    }
    return reply(result, result.status === "error" ? 404 : 200)
  } catch (e) {
    return reply({ status: "error", error: { code: "fetch.fail", message: String((e as Error).message) } }, 502)
  }
}

async function resolve(url: string, opts: Options): Promise<object> {
  const host = new URL(url).hostname
  if (/(^|\.)tiktok\.com$/.test(host)) return tiktok(url, opts)
  // TikTok's newer share links (tt.site/t/…) redirect to tiktok.com: expand them first.
  if (/(^|\.)tt\.site$/.test(host)) return tiktok(await expand(url), opts)
  if (/(^|\.)instagram\.com$/.test(host)) {
    const post = await instagram(url, opts).catch(() => null)
    if (post) return post
  }
  let info: any
  try {
    info = await runYtDlp(url, opts)
  } catch (e) {
    const image = opts.mode === "video" ? await pageImage(url).catch(() => null) : null
    if (image) return image
    throw e
  }
  const items = (info.entries ?? [info]).filter((e: any) => e?.url)
  if (!items.length) return { status: "error", error: { code: "content.not_found" } }
  if (items.length === 1) {
    const [e] = items
    return {
      status: "redirect", type: typeOf(e, opts.mode), url: e.url,
      filename: `${e.id ?? "file"}.${e.ext ?? "mp4"}`, title: e.title ?? info.title, thumbnail: e.thumbnail ?? info.thumbnail,
    }
  }
  return { status: "picker", title: info.title, picker: items.map((e: any) => ({ type: typeOf(e, opts.mode), url: e.url, thumb: e.thumbnail })) }
}

export const config: Config = { path: "/api", method: ["GET", "POST"] }
