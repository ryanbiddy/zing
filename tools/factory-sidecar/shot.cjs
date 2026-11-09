// Screenshot + scroll-recording helper for myzing.factory.visuals.
// Usage: node shot.cjs <url> <out.png> [framesDir]
// 1) renders <url> at 1280x900 and writes a viewport PNG;
// 2) if framesDir is given, switches to 1280x800 and records a smooth 6 s scroll as 180 JPEG frames
//    (f0000.jpg..f0179.jpg, 30 fps when encoded) - deterministic, so capture speed doesn't matter;
// 3) prints one JSON line: {ok, title, og_image, og_video, final_url, http_status, blocked, frames, scroll_px, error}.
// The page is untrusted: we only render it and read a few meta tags; nothing from it is executed here.
"use strict";
const { lookup } = require("dns").promises;
const { isIP } = require("net");

const CHROME = process.env.ZING_BROWSER_PATH;
const [, , url, outPath, framesDir] = process.argv;
const FRAMES = 180;
const MAX_SCROLL = 2400;
// Ads and trackers never load: a news page's picture is its story, not someone else's ad. Nor do loopback and
// private addresses, which a public page has no business reaching.
const AD = /(^|\.)(doubleclick\.net|googlesyndication\.com|googleadservices\.com|googletagservices\.com|adservice\.google\.[a-z.]+|imasdk\.googleapis\.com|amazon-adsystem\.com|adnxs\.com|taboola\.com|outbrain\.com|criteo\.(com|net)|pubmatic\.com|rubiconproject\.com|openx\.net|adsrvr\.org|moatads\.com|teads\.tv|sharethrough\.com|3lift\.com|triplelift\.com|indexww\.com|casalemedia\.com|smartadserver\.com|adform\.net|media\.net|yieldmo\.com|zemanta\.com|revcontent\.com|mgid\.com|bidswitch\.net|lijit\.com|sovrn\.com|33across\.com|gumgum\.com|connatix\.com|primis\.tech|springserve\.com|spotxchange\.com|innovid\.com|adsafeprotected\.com|doubleverify\.com|adroll\.com|nativo\.com|kargo\.com|seedtag\.com|ezoic\.net|ezojs\.com|mediavine\.com|adthrive\.com|freestar\.com|vdo\.ai|aniview\.com|minutemedia-prebid\.com|ads-twitter\.com)$/i;
const PRIVATE = /^(localhost|.*\.localhost|127\.\d+\.\d+\.\d+|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+|172\.(1[6-9]|2\d|3[01])\.\d+\.\d+|169\.254\.\d+\.\d+|0\.0\.0\.0|\[?::1?\]?|\[?f[cd][0-9a-f]*:.*|\[?fe80:.*)$/i;
const TRACKER = /(^|\.)(google-analytics\.com|googletagmanager\.com|parsely\.com|facebook\.net|hotjar\.com|segment\.(io|com)|scorecardresearch\.com|dap\.digitalgov\.gov)$/i;

function isPrivate(address) {
  const ip = address.replace(/^\[|\]$/g, "");
  const family = isIP(ip);
  if (family === 4) {
    const [a, b, c, d] = ip.split(".").map(Number);
    return a === 127 || a === 10 || (a === 172 && b >= 16 && b <= 31) ||
      (a === 192 && b === 168) || (a === 169 && b === 254) || (a === 100 && b >= 64 && b <= 127) ||
      (a === 0 && b === 0 && c === 0 && d === 0) || (a >= 224 && a <= 239);
  }
  if (family !== 6) return true;
  const hex = ip.split("%")[0].replace(/\d+\.\d+\.\d+\.\d+$/, v => {
    const [a, b, c, d] = v.split(".").map(Number);
    return `${((a << 8) | b).toString(16)}:${((c << 8) | d).toString(16)}`;
  });
  const halves = hex.split("::").map(v => v ? v.split(":") : []);
  const words = (halves.length === 2 ?
    [...halves[0], ...Array(8 - halves[0].length - halves[1].length).fill("0"), ...halves[1]] : halves[0])
    .map(v => parseInt(v, 16));
  if (words.slice(0, 7).every(v => v === 0) && words[7] <= 1) return true;
  if (words.slice(0, 5).every(v => v === 0) && (words[5] === 0 || words[5] === 0xffff)) {
    return isPrivate(`${words[6] >> 8}.${words[6] & 255}.${words[7] >> 8}.${words[7] & 255}`);
  }
  return (words[0] & 0xfe00) === 0xfc00 || (words[0] & 0xffc0) === 0xfe80 || (words[0] & 0xff00) === 0xff00;
}

async function main() {
  const res = { ok: false, title: null, og_image: null, og_video: null, final_url: null, blocked: false,
                http_status: null, frames: 0, scroll_px: 0, error: null };
  if (!url || !outPath || !/^https?:\/\//i.test(url)) {
    res.error = "usage: node shot.cjs <http(s) url> <out.png> [framesDir]";
    console.log(JSON.stringify(res));
    process.exit(2);
  }
  let browser;
  try {
    const { chromium } = require("playwright-core");
    browser = await chromium.launch({ executablePath: CHROME, headless: true });
    const ctx = await browser.newContext({
      viewport: { width: 1280, height: 900 },
      deviceScaleFactor: 1,
      userAgent:
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36 zing-factory/0.1",
      acceptDownloads: false,
      serviceWorkers: "block",
    });
    let first = true;
    const hosts = new Map();
    await ctx.routeWebSocket(/.*/, ws => ws.close());
    await ctx.route("**/*", async (route) => {
      let host = "";
      try { host = new URL(route.request().url()).hostname.replace(/^\[|\]$/g, "").replace(/\.$/, ""); } catch (_) {}
      if (AD.test(host) || TRACKER.test(host) || PRIVATE.test(host)) return route.abort();
      if (host) {
        if (isIP(host)) {
          if (isPrivate(host)) return route.abort();
        } else {
          if (!hosts.has(host)) hosts.set(host, lookup(host, {all: true, verbatim: true})
            .then(rows => rows.length > 0 && rows.every(row => !isPrivate(row.address))).catch(() => false));
          if (!await hosts.get(host)) return route.abort();
        }
      }
      await route.continue();
      if (host) {
        if (!first) console.log(JSON.stringify({network: {at: new Date().toISOString(), host}}));
        first = false;                              // the Python caller records the first navigation
      }
    });
    const page = await ctx.newPage();
    const response = await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    res.http_status = response ? response.status() : null;
    res.final_url = page.url();
    if (!response || res.http_status >= 400)
      throw new Error(response ? `HTTP ${res.http_status}` : "page navigation returned no response");
    try { await page.waitForLoadState("networkidle", { timeout: 10000 }); } catch (_) {}
    await page.waitForTimeout(1500);
    res.final_url = page.url();
    res.title = await page.title();
    const meta = await page.evaluate(() => {
      const get = (sel) => { const m = document.querySelector(sel); return m ? m.getAttribute("content") : null; };
      return {
        og_image: get('meta[property="og:image"], meta[name="og:image"], meta[name="twitter:image"]'),
        og_video: get('meta[property="og:video:secure_url"], meta[property="og:video:url"], meta[property="og:video"], meta[name="twitter:player:stream"]'),
        text: (document.body ? document.body.innerText : "").slice(0, 600),
      };
    });
    res.og_image = meta.og_image;
    res.og_video = meta.og_video;
    res.blocked = /just a moment|attention required|access denied|are you a robot|verify you are human|captcha|enable javascript and cookies/i
      .test(`${res.title} ${meta.text}`);
    // Hide cookie/consent overlays for the picture only. Nothing is clicked or accepted.
    await page.addStyleTag({ content: `
      #onetrust-consent-sdk, #onetrust-banner-sdk, .ot-sdk-container, #CybotCookiebotDialog, #didomi-host,
      .fc-consent-root, .cc-window, .cc-banner, #cookie-law-info-bar, .cookie-notice, #truste-consent-track,
      #usercentrics-root, #qc-cmp2-container, .osano-cm-window, #hs-eu-cookie-confirmation, .cky-consent-container,
      [id*="cookie-banner" i], [class*="cookie-banner" i], [id*="cookieconsent" i], [class*="cookieconsent" i],
      [id*="consent-banner" i], [class*="consent-banner" i], [aria-label*="cookie" i][role="dialog"],
      [aria-label*="consent" i][role="dialog"],
      [id^="div-gpt-ad"], [id^="google_ads"], ins.adsbygoogle, [data-ad-slot], [data-google-query-id], .OUTBRAIN,
      [id*="taboola" i], [class*="taboola" i], [class*="outbrain" i], [aria-label="advertisement" i],
      [class*="ad-slot" i], [id*="ad-slot" i], [class*="adSlot"], [class*="ad-container" i], [class*="ad-wrapper" i]
      { display: none !important; }
      html, body { overflow: auto !important; }` }).catch(() => {});
    await page.evaluate(() => {               // generic: fixed full-width bars that talk about cookies
      for (const el of document.querySelectorAll("body *")) {
        const cs = getComputedStyle(el);
        if ((cs.position === "fixed" || cs.position === "sticky") && el.offsetHeight > 40 &&
            /cookie|consent|privacy choices/i.test((el.innerText || "").slice(0, 400))) el.style.setProperty("display", "none", "important");
      }
    }).catch(() => {});
    await page.waitForTimeout(200);
    await page.screenshot({ path: outPath, fullPage: false, type: "png" });
    if (framesDir && !res.blocked) {
      await page.setViewportSize({ width: 1280, height: 800 });
      const maxScroll = await page.evaluate(() => {   // stop where the article or main content ends, not in the footer
        const all = Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0);
        const main = document.querySelector("article, main, [role='main']");
        const end = main ? main.getBoundingClientRect().bottom + window.scrollY : all;
        return Math.min(all, end > window.innerHeight ? end : all) - window.innerHeight;
      });
      const dist = Math.min(Math.max(maxScroll, 0), MAX_SCROLL);
      if (dist >= 300) {
        for (let y = 0; y <= dist; y += 400) {  // wake lazy-loaded images, then return to the top
          await page.evaluate((v) => window.scrollTo({ top: v, behavior: "instant" }), y);
          await page.waitForTimeout(120);
        }
        await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
        await page.waitForTimeout(800);
        for (let i = 0; i < FRAMES; i++) {
          const t = i / (FRAMES - 1);
          const e = t < 0.5 ? 4 * t * t * t : 1 - Math.pow(-2 * t + 2, 3) / 2;  // ease in-out
          await page.evaluate((v) => window.scrollTo({ top: v, behavior: "instant" }), Math.round(e * dist));
          await page.screenshot({ path: `${framesDir}/f${String(i).padStart(4, "0")}.jpg`, type: "jpeg", quality: 82 });
        }
        res.frames = FRAMES;
        res.scroll_px = dist;
      }
    }
    res.ok = true;
  } catch (e) {
    res.error = String(e && e.message ? e.message : e).split("\n")[0].slice(0, 300);
  } finally {
    if (browser) await browser.close().catch(() => {});
  }
  console.log(JSON.stringify(res));
}

if (require.main === module) main();
else module.exports = {isPrivate};
