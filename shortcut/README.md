# Save Video — my own "download from any link" Shortcut

Copy or share a link from **TikTok, Instagram, YouTube, X/Twitter, Facebook, Reddit,
Pinterest, Snapchat, Vimeo, Twitch clips** and more → the video is saved to Photos,
without watermark. Carousels / slideshows save every item.

It replaces "SnapVideo", which sent every link through `api.phimtat.vn`.

| Link | Handled by |
| --- | --- |
| TikTok | `tikwm.com` — works right away, no setup |
| Everything else | **your own cobalt server** ([cobalt](https://github.com/imputnet/cobalt), open source) |

> The official `api.cobalt.tools` blocks apps like Shortcuts, so you run your own copy (step 1).

## 1. Run your cobalt server

Any machine with Docker and a public https address (a small VPS, or a home server behind
Cloudflare Tunnel) works:

```sh
cd server
# edit API_URL in docker-compose.yml to your https address
docker compose up -d
```

Optional — make it private: copy `keys.example.json` to `keys.json`, replace the key with
your own UUID (`uuidgen`), and uncomment the auth lines in `docker-compose.yml`.

## 2. Build the Shortcut on iPhone (~5 min)

Shortcuts → **+** → name it **Save Video**, then add:

1. **Text** — `https://cobalt.your-domain.com/` (your server)
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
        (+ `Authorization` = `Api-Key YOUR-KEY` if you made it private)
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
python3 build_shortcut.py https://cobalt.your-domain.com/ [API_KEY]
shortcuts sign -m anyone -i SaveVideo.shortcut -o SaveVideo-signed.shortcut
```

AirDrop the signed file to your iPhone — iOS will not import an unsigned one.

## Notes
- YouTube often blocks servers in data centers; a home server usually works better for it.
- If something fails, add **Quick Look** after the cobalt request to see its error message.
- Only download content you have the right to save.
