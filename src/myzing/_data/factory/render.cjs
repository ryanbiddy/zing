const { chromium } = require(require.resolve("playwright-core", { paths: [process.cwd(), __dirname] }));
const fs = require("fs"), path = require("path"), url = require("url");
(async () => {
  const [scene, dataPath, outdir] = process.argv.slice(2);
  const DATA = JSON.parse(fs.readFileSync(dataPath, "utf8"));
  fs.mkdirSync(outdir, { recursive: true });
  const browser = await chromium.launch({ executablePath: process.env.ZING_BROWSER_PATH,
    args: ["--allow-file-access-from-files"] });
  try {
    const page = await browser.newPage({ viewport: { width: DATA.W || 1080, height: DATA.H || 1920 } });
    let error;
    page.on("pageerror", e => { error = e; });
    await page.addInitScript(d => { window.DATA = d; }, DATA);
    await page.goto(url.pathToFileURL(path.resolve(scene)).href);
    await page.evaluate(async () => { for (const w of [600, 800, 900]) await document.fonts.load(`${w} 40px Inter`); await document.fonts.ready; });
    if (error) throw error;
    if (DATA.captureFrames) fs.writeFileSync(path.join(outdir, "captions.json"), JSON.stringify(await page.evaluate(() => window.captionCues())));
    const n = Math.round(DATA.duration * DATA.fps), t0 = Date.now();
    const png = DATA.overlay || DATA.speakerLayer || DATA.captureFrames;
    for (const i of DATA.captureFrames || Array.from({ length: n }, (_, i) => i)) {
      await page.evaluate(t => window.seek(t), i / DATA.fps);
      if (error) throw error;
      const name = String(i + 1).padStart(5, "0");
      await page.screenshot({ path: path.join(outdir, name + (png ? ".png" : ".jpg")),
        ...(png ? { type: "png", omitBackground: true } : { type: "jpeg", quality: 93 }) });
      if (DATA.overlay && ((DATA.theme || {}).grain || await page.evaluate(() => window.exportFront))) {
        const front = await page.evaluate(() => window.exportFront);
        for (const layer of ["normal", "speaker", ...(front ? ["matte"] : [])]) {
          const dir = path.join(outdir, layer); fs.mkdirSync(dir, { recursive: true });
          await page.evaluate(l => window.exportLayer(l), layer === "normal" ? "" : layer);
          await page.screenshot({ path: path.join(dir, name + ".png"), type: "png", omitBackground: true });
        }
        await page.evaluate(() => window.exportLayer("overlay"));
      }
    }
    console.log("frames", DATA.captureFrames ? DATA.captureFrames.length : n, ((Date.now() - t0) / 1000).toFixed(0) + "s");
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
