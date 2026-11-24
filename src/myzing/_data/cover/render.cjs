"use strict";
const fs = require("node:fs");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const {chromium} = require(require.resolve("playwright-core", {paths: [process.cwd()]}));

async function main() {
  const [scene, jobFile, out] = process.argv.slice(2);
  const job = JSON.parse(fs.readFileSync(jobFile, "utf8"));
  const sceneURL = pathToFileURL(scene).href;
  const fonts = new URL("../fonts/", sceneURL);
  const allowed = new Set([sceneURL, job.spec.frame.src, ...job.fonts.map(f => new URL(f, fonts).href)]);
  const failures = [];
  const browser = await chromium.launch({executablePath: process.env.ZING_BROWSER_PATH,
    args: ["--allow-file-access-from-files", "--disable-background-networking",
      "--disable-gpu", "--force-color-profile=srgb"]});
  async function pageAt(scale) {
    const context = await browser.newContext({deviceScaleFactor: scale, offline: true, serviceWorkers: "block"});
    await context.route(/.*/, route => {
      const url = route.request().url();
      if (url.startsWith("file:///") && allowed.has(url)) return route.continue();
      failures.push("Blocked resource: " + url);
      return route.abort();
    });
    await context.routeWebSocket(/.*/, socket => {
      failures.push("Blocked WebSocket: " + socket.url());
      socket.close();
    });
    const page = await context.newPage();
    page.on("pageerror", error => failures.push(error.message));
    await page.exposeFunction("blockedResource", url => failures.push("Blocked resource: " + url));
    await page.addInitScript(() => document.addEventListener("securitypolicyviolation",
      event => window.blockedResource(event.blockedURI)));
    await page.goto(sceneURL);
    return page;
  }
  function checkPage() {
    if (failures.length) throw Error(failures.join("\n"));
  }
  try {
    const page = await pageAt(job.scale);
    const files = [];
    for (const item of job.items) {
      const {style, size, w, h, placement} = item;
      await page.setViewportSize({width:w, height:h});
      const layout = await page.evaluate(([spec, style, w, h]) => window.build(spec, style, w, h),
        [{...job.spec, placement}, style, w, h]);
      await page.evaluate(() => new Promise(done => requestAnimationFrame(() => requestAnimationFrame(done))));
      const file = style + "-" + size + "." + job.format;
      const options = job.format === "jpg" ? {type:"jpeg", quality:92} : {type:"png"};
      let bytes = await page.screenshot(options);
      if (size === "wide" && options.type === "jpeg") {
        while (bytes.length >= 2000000 && options.quality > 1) {
          options.quality = Math.max(1, options.quality - 5);
          bytes = await page.screenshot(options);
        }
        if (bytes.length >= 2000000) throw Error(file + ": try --scale 1 to keep the JPEG under 2 MB.");
      }
      checkPage();
      fs.writeFileSync(path.join(out, file), bytes);
      files.push({file, style, size, width:w*job.scale, height:h*job.scale, bytes:bytes.length,
        quality:options.quality, layout});
      allowed.add(pathToFileURL(path.join(out, file)).href);
    }

    const sheet = await pageAt(1);
    const columns = Math.min(job.sizes.length, 4);
    const width = columns * 288, height = Math.ceil(files.length / columns) * 260;
    await sheet.setViewportSize({width, height});
    await sheet.evaluate(async ({items, columns}) => {
      const stage = document.getElementById("stage");
      stage.style.cssText = `background:#17181b;color:white;display:grid;grid-template-columns:repeat(${columns},288px);font:16px Plex,sans-serif;`;
      for (const item of items) {
        const card = document.createElement("div");
        card.style.cssText = "padding:12px;height:260px;";
        const img = document.createElement("img");
        img.style.cssText = "display:block;width:264px;height:210px;object-fit:contain;margin-bottom:7px";
        img.src = item.url;
        card.append(img, item.style + " / " + item.size);
        stage.append(card);
        await img.decode();
      }
      await document.fonts.ready;
    }, {columns, items:files.map(f => ({...f, url:pathToFileURL(path.join(out, f.file)).href}))});
    const sheetFile = "sheet.jpg";
    const sheetBytes = await sheet.screenshot({type:"jpeg", quality:90});
    checkPage();
    fs.writeFileSync(path.join(out, sheetFile), sheetBytes);
    console.log(JSON.stringify({files, sheet:{file:sheetFile, width, height, bytes:sheetBytes.length, quality:90}}));
  } finally {
    await browser.close();
  }
}
main().catch(error => { console.error(error.message); process.exitCode = 1; });
