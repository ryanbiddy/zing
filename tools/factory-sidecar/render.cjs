// node render.cjs <scene.html> <data.json> <outdir>   -> outdir/00001.jpg ... (browser: ZING_BROWSER_PATH)
const { chromium } = require("playwright-core");
const fs = require("fs"), path = require("path"), url = require("url");
(async () => {
  const [scene, dataPath, outdir] = process.argv.slice(2);
  const DATA = JSON.parse(fs.readFileSync(dataPath, "utf8"));
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.ZING_BROWSER_PATH,
    args: ["--allow-file-access-from-files"] });
  const page = await browser.newPage({ viewport: { width: DATA.W || 1080, height: DATA.H || 1920 },
    deviceScaleFactor: DATA.scale || 1, offline: true, serviceWorkers: "block" });
  await page.route(/^https?:\/\//, route => route.abort());  // scene assets are local
  page.on("pageerror", e => console.log("pageerror:", e.message));
  await page.addInitScript(d => { window.DATA = d; }, DATA);
  await page.goto(url.pathToFileURL(path.resolve(scene)).href);
  await page.evaluate(async () => { for (const w of [600, 800, 900]) await document.fonts.load(`${w} 40px Inter`); await document.fonts.ready; });
  const n = Math.round(DATA.duration * DATA.fps);
  const t0 = Date.now();
  for (let i = 0; i < n; i++) {
    await page.evaluate(t => window.seek(t), i / DATA.fps);
    await page.screenshot({ path: path.join(outdir, `${String(i + 1).padStart(5, "0")}.jpg`), type: "jpeg", quality: 93 });
  }
  console.log("frames", n, ((Date.now() - t0) / 1000).toFixed(0) + "s");
  await browser.close();
})();
