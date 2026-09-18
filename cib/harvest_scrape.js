/* Reusable product-tile scraper for a harvest session.
 *
 * Paste into the browser pane's javascript_tool on a collection / category /
 * "all products" page. It scrolls to load lazy content, then dumps every
 * plausible product image with its context (alt text, nearest link, nearest
 * heading) so you can filter it down to a harvest_input list.
 *
 * Tune the three consts at the top per site, then:
 *   1. run it, copy the JSON
 *   2. keep the rows you want; map to {name, sourceUrl, brand?, category?}
 *   3. save as customers/<c>/harvest_input.csv  (or .json)
 *   4. `cib harvest --customer <c>`  (add --width 1400 for /media/ CDNs)
 *
 * Returns: { url, count, items: [{src, alt, link, heading, w, h}] }
 */
(async () => {
  const SCROLLS = 6;                 // times to page to the bottom
  const MIN_PX = 120;                // ignore icons/thumbnails smaller than this
  const SRC_MUST_MATCH = null;       // e.g. /\/media\/|syncpigeon/  — or null for any

  // strip known image-proxy prefixes so you get the real origin URL
  const unproxy = (s) => {
    s = s.replace(/^https?:\/\/img\.thelasthunt\.com\//, "");
    try { s = decodeURIComponent(s); } catch (e) {}
    return s.split("?")[0];
  };
  const near = (el, sel) => {
    for (let n = el; n && n !== document.body; n = n.parentElement) {
      const hit = n.querySelector ? n.querySelector(sel) : null;
      if (hit && hit.textContent.trim()) return hit.textContent.trim().replace(/\s+/g, " ");
      if (n.matches && n.matches(sel) && n.textContent.trim())
        return n.textContent.trim().replace(/\s+/g, " ");
    }
    return "";
  };
  const nearHref = (el) => {
    for (let n = el; n && n !== document.body; n = n.parentElement)
      if (n.tagName === "A" && n.getAttribute("href")) return n.getAttribute("href");
    return "";
  };

  for (let i = 0; i < SCROLLS; i++) {
    window.scrollTo(0, document.body.scrollHeight);
    await new Promise((r) => setTimeout(r, 900));
  }
  window.scrollTo(0, 0);

  const seen = new Set();
  const items = [];
  document.querySelectorAll("img").forEach((img) => {
    const raw = img.currentSrc || img.src || "";
    if (!raw) return;
    if (SRC_MUST_MATCH && !SRC_MUST_MATCH.test(raw)) return;
    const src = unproxy(raw);
    const w = img.naturalWidth || 0, h = img.naturalHeight || 0;
    if (w && h && (w < MIN_PX || h < MIN_PX)) return;
    if (/logo|sprite|icon|placeholder|banner|swatch|payment/i.test(src)) return;
    if (seen.has(src)) return;
    seen.add(src);
    items.push({
      src,
      alt: (img.alt || "").trim(),
      link: nearHref(img),
      heading: near(img, "h1,h2,h3,h4,[class*=title i],[class*=name i],strong"),
      w, h,
    });
  });

  return JSON.stringify({ url: location.href, count: items.length, items }, null, 1);
})();
