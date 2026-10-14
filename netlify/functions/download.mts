// POST /api {"url": "<post link>"} -> cobalt-style JSON:
//   {status: "redirect", url}            one video
//   {status: "picker", picker: [{url}]}  carousel / slideshow
//   {status: "error", error: {code}}
// If the API_KEY env var is set, requests need the header "Authorization: Api-Key <key>".
import type { Config } from "@netlify/functions"
import { execFile } from "node:child_process"
import { chmodSync, copyFileSync, existsSync } from "node:fs"
import { join } from "node:path"

const BIN = "/tmp/yt-dlp"
// One file with both audio and video, over plain https, mp4 if possible — what Photos can save.
const FORMAT = "b[ext=mp4][protocol^=http]/b[protocol^=http]/b"

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

function runYtDlp(url: string): Promise<any> {
  const args = ["-J", "-f", FORMAT, "--no-warnings", "--no-cache-dir", "--playlist-end", "20", url]
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

const reply = (body: object, status = 200) => Response.json(body, { status })
const fail = (code: string, status = 400) => reply({ status: "error", error: { code } }, status)

export default async (req: Request) => {
  const key = Netlify.env.get("API_KEY")
  if (key && req.headers.get("authorization") !== `Api-Key ${key}`) return fail("auth.key.invalid", 401)

  let url = new URL(req.url).searchParams.get("url")
  if (req.method === "POST") url = (await req.json().catch(() => ({}))).url ?? url
  if (!url || !/^https?:\/\//.test(url)) return fail("link.missing")

  try {
    const info = await runYtDlp(url)
    const links = (info.entries ?? [info]).map((e: any) => e?.url).filter(Boolean)
    if (!links.length) return fail("content.not_found", 404)
    if (links.length === 1) return reply({ status: "redirect", url: links[0], filename: `${info.id ?? "video"}.${info.ext ?? "mp4"}` })
    return reply({ status: "picker", picker: links.map((u: string) => ({ type: "video", url: u })) })
  } catch (e) {
    return reply({ status: "error", error: { code: "fetch.fail", message: String((e as Error).message) } }, 502)
  }
}

export const config: Config = { path: "/api", method: ["GET", "POST"] }
