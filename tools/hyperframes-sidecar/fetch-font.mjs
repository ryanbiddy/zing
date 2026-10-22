// Explicit setup only; never imported by the renderer or tests.
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { createHash } from 'node:crypto';
import { fileURLToPath } from 'node:url';
const source = JSON.parse(readFileSync(new URL('./font-source.json', import.meta.url)));
const target = resolve(process.argv[2] ?? fileURLToPath(new URL('../../zing-workspace/hyperframes/fonts/', import.meta.url)));
mkdirSync(target, { recursive: true });
for (const item of [source.notice, source.font]) {
  const path = join(target, item.file);
  let bytes;
  if (existsSync(path)) bytes = readFileSync(path);
  else {
    console.log(`Downloading ${item.url}`);
    const response = await fetch(item.url, { signal: AbortSignal.timeout(30000) });
    if (!response.ok) throw Error(`Download failed: HTTP ${response.status}`);
    bytes = Buffer.from(await response.arrayBuffer());
  }
  const hash = createHash('sha256').update(bytes).digest('hex');
  if (hash !== item.sha256) throw Error(`SHA-256 mismatch for ${path}; remove the bad file and retry setup.`);
  writeFileSync(path, bytes);
  console.log(`${source.license} ${hash} ${path}`);
}
