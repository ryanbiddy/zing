import { openSync, closeSync, writeFileSync, copyFileSync, linkSync, renameSync, unlinkSync, lstatSync, mkdirSync, fsyncSync } from 'node:fs';
import { dirname, join, basename } from 'node:path';
import { randomUUID } from 'node:crypto';

export function reserveOutput(output, overwrite = false) {
  mkdirSync(dirname(output), { recursive: true });
  const lock = output + '.publish-lock';
  const fd = openSync(lock, 'wx'); closeSync(fd);
  try {
    if (!overwrite) for (const path of [output, output + '.receipt.json']) {
      try { lstatSync(path); } catch (e) { if (e.code === 'ENOENT') continue; throw e; }
      throw Error(`Output or receipt already exists: ${path}; use --overwrite explicitly`);
    }
  } catch (e) { unlinkSync(lock); throw e; }
  return () => unlinkSync(lock);
}

export function atomicPublish(source, destination, overwrite = false) {
  const stage = join(dirname(destination), `.${basename(destination)}.${randomUUID()}.part`);
  try {
    copyFileSync(source, stage, 1 /* COPYFILE_EXCL */);
    const fd = openSync(stage, 'r+');
    try { fsyncSync(fd); } finally { closeSync(fd); }
    // link is the no-clobber commit, even against non-cooperating writers.
    if (overwrite) renameSync(stage, destination);
    else linkSync(stage, destination);
  } finally {
    try { unlinkSync(stage); } catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
}

export function publishPair(source, output, receipt, overwrite = false) {
  const stagedReceipt = source + '.publish.json';
  writeFileSync(stagedReceipt, JSON.stringify(receipt, null, 2) + '\n');
  atomicPublish(stagedReceipt, output + '.receipt.json', overwrite);
  try { atomicPublish(source, output, overwrite); }
  catch (e) { if (!overwrite) unlinkSync(output + '.receipt.json'); throw e; }
}
