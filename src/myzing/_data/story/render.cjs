// Capture a local cutout page with the factory's installed Playwright sidecar.
"use strict";
const { chromium } = require(require.resolve("playwright-core", { paths: [process.cwd(), __dirname] }));
const fs = require("fs"), path = require("path"), { pathToFileURL } = require("url");

(async () => {
  const [scene, dataPath, outdir] = process.argv.slice(2);
  const data = JSON.parse(fs.readFileSync(dataPath, "utf8"));
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.ZING_BROWSER_PATH,
    args: ["--allow-file-access-from-files", "--disable-gpu"] });
  try {
    const page = await browser.newPage({ viewport: { width: 1080, height: 1920 },
      deviceScaleFactor: 1, offline: true, serviceWorkers: "block" });
    await page.route(/^https?:\/\//, route => route.abort());
    await page.routeWebSocket(/.*/, ws => ws.close());
    let error;
    page.on("pageerror", e => { error = e; });
    await page.goto(pathToFileURL(path.resolve(scene)).href);
    await page.evaluate(d => window.build(d.story, d.timings, d.base, d.vocabulary), data);
    if (error) throw error;
    const times = data.stills || Array.from({ length: Math.ceil(data.timings.duration * 30) }, (_, i) => i / 30);
    for (let i = 0; i < times.length; i++) {
      await page.evaluate(t => window.seek(t), times[i]);
      if (error) throw error;
      await page.screenshot({ path: path.join(outdir, String(i + 1).padStart(5, "0") + ".jpg"),
        type: "jpeg", quality: 93 });
    }
    console.log("frames", times.length);
  } finally {
    await browser.close();
  }
})().catch(e => { console.error(e); process.exitCode = 1; });
