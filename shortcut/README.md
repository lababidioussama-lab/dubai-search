# Save TikTok — my own video-saver Shortcut

Share a TikTok link → the video (no watermark) is saved to Photos.
It replaces the "SnapVideo" shortcut, which routed every link through `api.phimtat.vn`.
This one talks directly to the public TikTok resolver `tikwm.com` and nothing else.

## Option A — build it by hand on iPhone (recommended, ~3 min)

Open **Shortcuts → +**, name it **Save TikTok**, then add these actions in order:

1. **Match Text** — pattern `https?://\S+`, in **Shortcut Input**
2. **Get Item from List** — **First Item** of **Matches**
3. **Get Contents of URL** — URL `https://www.tikwm.com/api/`
   - Method: **POST**, Request Body: **Form**
   - Field `url` = **Item from List**
   - Field `hd` = `1`
4. **Get Dictionary Value** — **Value** for key `data.play` in **Contents of URL**
5. **Get Contents of URL** — URL = **Dictionary Value**
6. **Save to Photo Album** — **Contents of URL** → Recents
7. **Show Notification** — "Video saved to Photos"

Then tap the **ⓘ** (details) button:
- Turn on **Show in Share Sheet**, accept **URLs** and **Text**
- Set **If there's no input** → **Get Clipboard**

**Use it:** in TikTok tap **Share → More → Save TikTok**, or copy the link and run the shortcut.

## Option B — generate the file (needs a Mac to sign)

```sh
python3 build_shortcut.py
shortcuts sign -m anyone -i SaveTikTok.shortcut -o SaveTikTok-signed.shortcut
```

AirDrop `SaveTikTok-signed.shortcut` to your iPhone. iOS will not import the unsigned file.

## Notes
- Photo slideshows (image posts) are not handled — only videos.
- For the watermarked version use key `data.wmplay`; for audio only use `data.music`.
- tikwm.com is a free third-party service; if it rate-limits you, wait a moment and retry.
