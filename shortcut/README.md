# Save Video — my own "download from any link" Shortcut

Copy or share a link from **TikTok, Instagram, YouTube, X/Twitter, Facebook, Reddit,
Pinterest, Snapchat, Vimeo, Twitch clips** and more → the video is saved to Photos,
without watermark. Carousels / slideshows save every item.

It replaces "SnapVideo", which sent every link through `api.phimtat.vn`.

| Link | Handled by |
| --- | --- |
| TikTok | `tikwm.com` — works right away, no setup |
| Everything else | **your own server** — `https://save-video-ol.netlify.app/api` |

## 1. Your server

The server is the Netlify function in [`netlify/functions/download.mts`](../netlify/functions/download.mts)
(project **save-video-ol**, see the main [README](../README.md) to put it online).
It requires the header `Authorization: Api-Key <your key>`.

### Alternative: a cobalt server with Docker

Any machine with Docker and a public https address (a small VPS, or a home server behind
Cloudflare Tunnel) can run [cobalt](https://github.com/imputnet/cobalt) instead — it is
stronger on YouTube. The Shortcut works with either:

```sh
cd server
# edit API_URL in docker-compose.yml to your https address
docker compose up -d
```

Optional — make it private: copy `keys.example.json` to `keys.json`, replace the key with
your own UUID (`uuidgen`), and uncomment the auth lines in `docker-compose.yml`.

## 2. Build the Shortcut on iPhone (~5 min)

Shortcuts → **+** → name it **Save Video**, then add:

1. **Text** — `https://save-video-ol.netlify.app/api` (your server)
2. **Match Text** — pattern `https?://\S+` in **Shortcut Input**
3. **Get Item from List** — **First Item** of **Matches**
4. **If** **Item from List** **contains** `tiktok.com`
   1. **Get Contents of URL** — `https://www.tikwm.com/api/`, Method **POST**, Body **Form**:
      `url` = **Item from List**, `hd` = `1`
   2. **Get Dictionary Value** — key `data.play`
   3. **Add to Variable** — `Links`
5. **Otherwise**
   1. **Get Contents of URL** — URL = **Text** (step 1), Method **POST**
      - Headers: `Accept` = `application/json`, `Content-Type` = `application/json`
        and `Authorization` = `Api-Key YOUR-KEY`
      - Body **JSON**: `url` = **Item from List**, `videoQuality` = `1080`
   2. **Get Dictionary Value** — key `status` → call it *Status*
   3. **If** *Status* **is** `picker`
      1. **Get Dictionary Value** — key `picker` in **Contents of URL**
      2. **Repeat with Each** item → **Get Dictionary Value** `url` in **Repeat Item**
         → **Add to Variable** `Links`
   4. **Otherwise**
      1. **Get Dictionary Value** — key `url` in **Contents of URL** → **Add to Variable** `Links`
   5. **End If**
6. **End If**
7. **Repeat with Each** item in **Links**
   1. **Get Contents of URL** — **Repeat Item**
   2. **Save to Photo Album** — **Contents of URL**
8. **End Repeat** → **Show Notification** "Saved to Photos"

Tap **ⓘ** → turn on **Show in Share Sheet** (URLs, Text) and set
**If there's no input → Get Clipboard**.

**Use it:** any app → **Share → Save Video**, or copy a link and run the shortcut
(or add it to your Home Screen / Back Tap).

## Or generate the file (needs a Mac to sign)

```sh
python3 build_shortcut.py https://save-video-ol.netlify.app/api YOUR-KEY
shortcuts sign -m anyone -i SaveVideo.shortcut -o SaveVideo-signed.shortcut
```

AirDrop the signed file to your iPhone — iOS will not import an unsigned one.

## Notes
- YouTube often blocks servers in data centers, and the Netlify server only gets YouTube's
  360p single-file version; use the cobalt option if YouTube matters to you.
- If something fails, add **Quick Look** after the cobalt request to see its error message.
- Only download content you have the right to save.
