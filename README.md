# Save Video

My own iOS Shortcut to save videos from any link (TikTok, Instagram, X, Facebook, Reddit,
Pinterest, Vimeo…) without watermark, plus the small server it talks to.

- [`shortcut/`](shortcut/) — how to build the Shortcut on iPhone
- [`netlify/functions/download.mts`](netlify/functions/download.mts) — the server:
  `POST /api {"url": "..."}` → direct video link, using [yt-dlp](https://github.com/yt-dlp/yt-dlp)

## Put the server online (one time)

The Netlify project **save-video-ol** already exists and has its `API_KEY` set.

1. Open https://app.netlify.com/projects/save-video-ol
2. **Project configuration → Build & deploy → Link repository** → GitHub →
   `dubai-search`, branch `claude/custom-shortcut-creation-n4b8hj` (or `main` once merged)
3. Leave the build settings as they are (they come from `netlify.toml`) → **Deploy**

Check it: open https://save-video-ol.netlify.app — it should say the server is running.

## Test locally

```sh
npm install
npx netlify dev   # then POST to http://localhost:8888/api
```
