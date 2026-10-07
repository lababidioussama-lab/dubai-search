(() => {
  const cfg = window.API_CONFIG;
  const $ = (id) => document.getElementById(id);
  const keyInput = $("apiKey");
  const form = $("searchForm");
  const status = $("status");
  const results = $("results");
  const locations = new Map(); // display name -> id
  let page = 1;

  try { keyInput.value = localStorage.getItem("rapidapiKey") || ""; } catch {}
  keyInput.addEventListener("change", () => {
    try { localStorage.setItem("rapidapiKey", keyInput.value.trim()); } catch {}
  });

  async function call(path, params) {
    const key = keyInput.value.trim();
    if (!key) throw new Error("Enter your RapidAPI key first.");
    const url = new URL(path, `https://${cfg.host}`);
    for (const [k, v] of Object.entries(params)) if (v !== "" && v != null) url.searchParams.set(k, v);
    const res = await fetch(url, { headers: { "X-RapidAPI-Key": key, "X-RapidAPI-Host": cfg.host } });
    const body = await res.json().catch(() => null);
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}${body?.message ? ` — ${body.message}` : ""}`);
    return body;
  }

  // The API's response shape isn't fixed here, so find the first array of objects.
  function findList(data) {
    if (Array.isArray(data)) return data;
    if (data && typeof data === "object") {
      for (const k of ["hits", "results", "data", "properties", "items", "listings"]) {
        const found = data[k] && findList(data[k]);
        if (found) return found;
      }
      for (const v of Object.values(data)) {
        if (Array.isArray(v) && v.some((x) => x && typeof x === "object")) return v;
      }
    }
    return null;
  }

  const pick = (o, ...keys) => {
    for (const k of keys) {
      const v = k.split(".").reduce((a, p) => (a == null ? a : a[p]), o);
      if (v != null && v !== "") return v;
    }
  };

  // Location autocomplete
  let timer;
  form.locationText.addEventListener("input", (e) => {
    clearTimeout(timer);
    const q = e.target.value.trim();
    if (q.length < 2 || locations.has(q)) return;
    timer = setTimeout(async () => {
      try {
        const { path, queryParam } = cfg.endpoints.autocomplete;
        const list = findList(await call(path, { [queryParam]: q })) || [];
        const dl = $("locationList");
        dl.innerHTML = "";
        for (const loc of list.slice(0, 10)) {
          const name = pick(loc, "name", "title", "location", "full_name") || "";
          const id = pick(loc, "id", "externalID", "location_id", "slug");
          if (!name || id == null) continue;
          locations.set(name, id);
          dl.append(new Option(name, name));
        }
      } catch (err) { status.textContent = `Autocomplete: ${err.message}`; }
    }, 300);
  });

  function card(p) {
    const title = pick(p, "title", "name", "title_l1") || "Property";
    const price = pick(p, "price", "price.value", "amount");
    const beds = pick(p, "rooms", "bedrooms", "beds");
    const baths = pick(p, "baths", "bathrooms");
    const area = pick(p, "area", "size", "area.value");
    const loc = pick(p, "location.name", "location", "community", "address");
    const img = pick(p, "coverPhoto.url", "cover_photo", "image", "images.0", "photos.0.url", "thumbnail");
    const link = pick(p, "url", "link", "share_url");
    const el = document.createElement("article");
    el.className = "listing";
    el.innerHTML = `${img ? `<img loading="lazy" alt="">` : ""}<div class="body"><h3></h3><div class="price"></div><div class="meta"></div></div>`;
    if (img) el.querySelector("img").src = typeof img === "string" ? img : img.url || "";
    const h = el.querySelector("h3");
    if (link) { const a = document.createElement("a"); a.href = link; a.target = "_blank"; a.rel = "noopener"; a.textContent = title; h.append(a); }
    else h.textContent = title;
    el.querySelector(".price").textContent = price != null ? `AED ${Number(price).toLocaleString()}` : "";
    el.querySelector(".meta").textContent = [
      typeof loc === "string" ? loc : Array.isArray(loc) ? loc.map((l) => l.name || l).join(", ") : "",
      beds != null ? `${beds == 0 ? "Studio" : beds + " bd"}` : "",
      baths != null ? `${baths} ba` : "",
      area != null ? `${Math.round(area)} sq ft` : "",
    ].filter(Boolean).join(" · ");
    return el;
  }

  async function search() {
    const f = new FormData(form);
    const s = cfg.endpoints.search;
    const text = (f.get("locationText") || "").trim();
    const values = {
      purpose: f.get("purpose"),
      location: locations.get(text) ?? text,
      category: f.get("category"),
      minPrice: f.get("minPrice"),
      maxPrice: f.get("maxPrice"),
      beds: f.get("beds"),
      page,
    };
    const params = {};
    for (const [field, apiName] of Object.entries(s.params)) params[apiName] = values[field];

    status.textContent = "Searching…";
    results.innerHTML = "";
    try {
      const data = await call(s.path, params);
      $("raw").textContent = JSON.stringify(data, null, 2);
      const list = findList(data) || [];
      list.forEach((p) => results.append(card(p)));
      status.textContent = list.length ? `Page ${page} — ${list.length} results` : "No results. Check the raw response below.";
      $("prev").hidden = page <= 1;
      $("next").hidden = list.length === 0;
    } catch (err) {
      status.textContent = `Error: ${err.message}`;
    }
  }

  form.addEventListener("submit", (e) => { e.preventDefault(); page = 1; search(); });
  $("prev").onclick = () => { page--; search(); };
  $("next").onclick = () => { page++; search(); };
})();
