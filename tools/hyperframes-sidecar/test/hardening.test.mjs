import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync, writeFileSync, mkdtempSync, rmSync, readdirSync, existsSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync, spawn } from 'node:child_process';
import { reserveOutput, atomicPublish, publishPair } from '../publish.mjs';
import { validatePlan } from '../plan.mjs';
import { composition } from '../templates.mjs';

const guard = fileURLToPath(new URL('../offline.cjs', import.meta.url));
for (const expression of [
  "require('net').connect({port:80,hostname:'example.invalid'})",
  "require('net').createConnection({port:80,hostname:'198.51.100.1'})",
  "new (require('net').Socket)().connect({port:80,hostname:'example.invalid'})",
  "require('net').connect({port:80,host:'localhost',hostname:'example.invalid'})",
  "require('tls').connect({port:443,hostname:'example.invalid'})",
  "require('tls').connect(443, {hostname:'example.invalid'})",
  "require('tls').connect({port:443,host:'127.0.0.1',servername:'example.invalid'})",
  "require('http').get('http://example.invalid/')",
  "require('http').request({hostname:'example.invalid',path:'/'})",
  "require('https').get({hostname:'example.invalid'})",
  "require('https').request(new URL('https://example.invalid/'))",
  "require('http2').connect('https://example.invalid/')",
  "fetch('https://example.invalid/')",
  "fetch(new Request('https://example.invalid/'))",
  "require('dns').lookup('example.invalid',()=>{})",
  "require('dns').resolve4('example.invalid',()=>{})",
  "require('dns').reverse('198.51.100.1',()=>{})",
  "require('dns').lookupService('198.51.100.1',80,()=>{})",
  "require('dns').promises.resolve4('example.invalid')",
  "require('dns').promises.lookup('example.invalid')",
  "new (require('dns').Resolver)().resolve4('example.invalid',()=>{})",
  "new (require('dns').promises.Resolver)().resolve4('example.invalid')",
  "require('dgram').createSocket('udp4')",
  "new (require('dgram').Socket)('udp4').send('x',80,'198.51.100.1')",
  "require('child_process').exec('curl https://example.invalid')",
  "require('child_process').execSync('curl https://example.invalid')",
  "require('child_process').execFile('curl',['https://example.invalid'])",
  "require('child_process').execFileSync('curl',['https://example.invalid'])",
  "require('child_process').spawn('curl',['https://example.invalid'])",
  "require('child_process').spawnSync(process.execPath,['-e',\"fetch('https://example.invalid')\"])",
  "require('child_process').fork('remote.js')",
  "require('child_process').spawn('powershell.exe',['-Command','Invoke-WebRequest https://example.invalid'])",
  "require('child_process').execFileSync('ldd',['/bin/sh'])",
  "require('child_process').execFileSync('ps',['-A','-ww','-o','pid=,ppid=,args=,env'])",
  "require('child_process').execFileSync('ps',['-U','0;id','-ww','-o','pid=,ppid=,args='])",
]) test(`guard denies ${expression}`, () => {
  const result = spawnSync(process.execPath, ['--require', guard, '-e', `require('assert').throws(()=>{${expression}}, /Offline render blocked/);`], { encoding: 'utf8', timeout: 10000 });
  assert.equal(result.status, 0, result.stderr);
});

test('guard allows local HTTP and denies a fetch redirect to an external origin', () => {
  const script = `
    const assert = require('assert'), http = require('http');
    const server = http.createServer((req,res) => {
      if(req.url === '/redirect') { res.writeHead(302,{Location:'https://example.invalid/'}); res.end(); }
      else res.end('local');
    });
    server.listen(0,'127.0.0.1', async()=>{
      try {
        const url = 'http://127.0.0.1:'+server.address().port;
        assert.equal(await (await fetch(url)).text(),'local');
        await assert.rejects(fetch(url+'/redirect'));
        const { connect } = await import('node:net');
        assert.throws(()=>connect({hostname:'example.invalid',port:80}), /Offline render blocked/);
      } finally { server.closeAllConnections(); server.close(); }
    });`;
  const result = spawnSync(process.execPath, ['--require', guard, '-e', script], { encoding: 'utf8', timeout: 10000 });
  assert.equal(result.status, 0, result.stderr);
});

function inTemp(fn) {
  const root = mkdtempSync(join(tmpdir(), 'hf-test-'));
  try { return fn(root); } finally { rmSync(root, { recursive: true }); }
}
test('existing receipt and concurrent reservation block publication', () => inTemp(root => {
  const out = join(root, 'out.mov');
  writeFileSync(out + '.receipt.json', 'keep');
  assert.throws(() => reserveOutput(out), /already exists/);
  assert.equal(readFileSync(out + '.receipt.json', 'utf8'), 'keep');
  const release = reserveOutput(out, true);
  try { assert.throws(() => reserveOutput(out, true), /EEXIST/); } finally { release(); }
  assert.ok(!existsSync(out));
}));
test('racing output cannot be clobbered; explicit overwrite replaces both files', () => inTemp(root => {
  const src = join(root, 'source'), out = join(root, 'out.mov');
  writeFileSync(src, 'new bytes');
  const release = reserveOutput(out);
  try {
    writeFileSync(out, 'racing writer');
    assert.throws(() => publishPair(src, out, {version:1}), /EEXIST/);
    assert.equal(readFileSync(out, 'utf8'), 'racing writer');
    assert.ok(!existsSync(out + '.receipt.json'));
  } finally { release(); }
  const replace = reserveOutput(out, true);
  try { publishPair(src, out, {version:1, complete:true}, true); } finally { replace(); }
  assert.equal(readFileSync(out, 'utf8'), 'new bytes');
  assert.equal(JSON.parse(readFileSync(out + '.receipt.json')).complete, true);
  assert.ok(!readdirSync(root).some(n => n.endsWith('.part')));
}));
test('receipt racing after reservation is preserved without publishing media', () => inTemp(root => {
  const src = join(root, 'source'), out = join(root, 'out.mov'); writeFileSync(src, 'bytes');
  const release = reserveOutput(out);
  try {
    writeFileSync(out + '.receipt.json', 'racer');
    assert.throws(() => publishPair(src, out, {}), /EEXIST/);
    assert.ok(!existsSync(out));
    assert.equal(readFileSync(out + '.receipt.json', 'utf8'), 'racer');
  } finally { release(); }
}));
test('simultaneous atomic publishers have exactly one complete winner', async () => {
  const root = mkdtempSync(join(tmpdir(), 'hf-race-'));
  try {
    const out = join(root, 'out'), sources = [join(root, 'a'), join(root, 'b')];
    sources.forEach((p,i) => writeFileSync(p, String(i).repeat(100000)));
    const module = new URL('../publish.mjs', import.meta.url).href;
    const results = await Promise.all(sources.map(src => new Promise(resolve => {
      const child = spawn(process.execPath, ['--input-type=module', '-e',
        `import {atomicPublish} from ${JSON.stringify(module)}; try { atomicPublish(${JSON.stringify(src)},${JSON.stringify(out)}); } catch(e) { process.exitCode = e.code === 'EEXIST' ? 2 : 3; }`], {stdio:'ignore'});
      child.on('exit', resolve);
    })));
    assert.deepEqual(results.sort(), [0,2]);
    const winner = readFileSync(out,'utf8');
    assert.ok(sources.some(p=>readFileSync(p,'utf8')===winner));
    assert.ok(!readdirSync(root).some(n=>n.endsWith('.part')));
  } finally { rmSync(root,{recursive:true}); }
});
test('font hash is checked again against the exact embedded bytes', () => inTemp(root => {
  const p = JSON.parse(readFileSync(new URL('../example-plan.json', import.meta.url)));
  const font = join(root, 'font.ttf'); writeFileSync(font, 'test');
  p.background = {transparent:true};
  p.captions.forEach(e => { e.style.font = font; e.style.font_sha256 = '0'.repeat(64); });
  assert.throws(()=>validatePlan(p), /SHA-256 mismatch/);
  assert.throws(()=>composition(p), /SHA-256 mismatch/);
}));
