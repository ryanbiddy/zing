// Defense in depth for the pinned CLI, not an OS sandbox for hostile code.
const fs = require('node:fs');
const net = require('node:net');
const tls = require('node:tls');
const dns = require('node:dns');
const cp = require('node:child_process');
const path = require('node:path');
const { syncBuiltinESMExports } = require('node:module');
if (process.env.ZING_HF_RUNTIME_HOME) require('node:os').homedir = () => process.env.ZING_HF_RUNTIME_HOME;
const local = host => ['localhost', '127.0.0.1', '::1', '[::1]'].includes(String(host).toLowerCase());
function denied(target) {
  const message = 'Offline render blocked external request or child process: ' + target;
  if (process.env.ZING_HF_NETWORK_LOG) fs.appendFileSync(process.env.ZING_HF_NETWORK_LOG, message + '\n');
  throw Error(message);
}
function hosts(options) {
  // Check BOTH names: hostname must never disappear behind a benign host.
  for (const key of ['host', 'hostname', 'servername']) {
    if (options[key] !== undefined && !local(options[key])) denied(options[key]);
  }
  if (options.path !== undefined) denied('IPC/socket path');
}
function socketArgs(args) {
  if (Array.isArray(args[0])) return socketArgs(args[0]);
  const first = args[0];
  if (first && typeof first === 'object') hosts(first);
  else if (typeof first === 'string') denied('IPC/socket path');
  else if (typeof args[1] === 'string' && !local(args[1])) denied(args[1]);
  for (const value of args.slice(1)) if (value && typeof value === 'object') hosts(value);
}
for (const [owner, key] of [[net, 'connect'], [net, 'createConnection'], [net.Socket.prototype, 'connect'], [tls, 'connect']]) {
  const original = owner[key];
  owner[key] = function (...args) { socketArgs(args); return original.apply(this, args); };
}
for (const module of ['node:http', 'node:https']) for (const key of ['request', 'get']) {
  const owner = require(module), original = owner[key];
  owner[key] = function (...args) {
    for (const value of args) {
      if (typeof value === 'string' || value instanceof URL) {
        const url = new URL(value); if (!local(url.hostname)) denied(url.hostname);
      } else if (value && typeof value === 'object') {
        const { path: resource, ...options } = value; hosts(options);
        if (options.socketPath) denied('HTTP socketPath');
      }
    }
    return original.apply(this, args);
  };
}
const h2 = require('node:http2'), h2connect = h2.connect;
h2.connect = function (authority, ...args) {
  if (!local(new URL(authority).hostname)) denied('HTTP/2 authority');
  return h2connect.call(this, authority, ...args);
};
function guardDNS(owner, allowLookup = false) {
  for (const key of Object.getOwnPropertyNames(owner)) {
    if (/^(resolve|reverse|lookup|setServers)/.test(key) && typeof owner[key] === 'function') {
      const original = owner[key];
      owner[key] = function (host, ...args) {
        if (!(allowLookup && key === 'lookup' && local(host))) denied('DNS ' + key);
        return original.call(this, host, ...args);
      };
    }
  }
}
guardDNS(dns, true); guardDNS(dns.promises, true);
guardDNS(dns.Resolver.prototype); guardDNS(dns.promises.Resolver.prototype);
const dgram = require('node:dgram');
dgram.createSocket = () => denied('UDP socket');
for (const key of ['connect', 'send', 'bind', 'addMembership', 'addSourceSpecificMembership']) {
  dgram.Socket.prototype[key] = () => denied('UDP ' + key);
}
const originalFetch = globalThis.fetch;
globalThis.fetch = (input, options) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (!local(url.hostname)) denied(url.hostname);
  return originalFetch(input, { ...options, redirect: 'error' });
};
// Only exact installed media tools and browser may launch. No arbitrary child scripts.
const real = command => { try { return fs.realpathSync(command); } catch { return null; } };
const browser = real(process.env.HYPERFRAMES_BROWSER_PATH ?? '');
const media = ['HYPERFRAMES_FFMPEG_PATH', 'HYPERFRAMES_FFPROBE_PATH'].map(k => real(process.env[k] ?? '')).filter(Boolean);
function childArgs(command, args, options) {
  if (!Array.isArray(args) || options?.shell) denied('shell or non-array child arguments');
  const binary = real(command);
  const worker = real(path.join(__dirname, 'node_modules/hyperframes/dist/renderSetupWorker.js'));
  if (binary === real(process.execPath) && worker && real(args[0]) === worker && args.length === 2 &&
      ['browser', 'lint', 'orphan-cleanup'].includes(args[1])) {
    return ['--require', __filename, ...args];
  }
  if (binary && binary === browser) return [...args,
    '--disable-background-networking', '--disable-component-update', '--disable-sync',
    '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=localhost;127.0.0.1;[::1]',
    '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost'];
  if (binary && media.includes(binary)) {
    if (args.some(a => /^(?:https?|tcp|tls|udp|rtmp|rtsp|srt|ftp):/i.test(a))) denied('media network protocol');
    for (let i = 0; i < args.length; i++) if (args[i] === '-protocol_whitelist' && !['file,pipe', 'file,pipe,fd'].includes(args[i + 1])) denied('media protocol override');
    return ['-protocol_whitelist', 'file,pipe,fd', ...args.flatMap(a =>
      a === '-i' ? ['-protocol_whitelist', 'file,pipe,fd', a] : [a])];
  }
  // Puppeteer local tree termination; remote /S is forbidden.
  if (process.platform === 'win32' && path.basename(command).toLowerCase() === 'taskkill' &&
      /^\/pid \d+ \/T \/F$/i.test(args.join(' '))) return args;
  if (process.platform === 'win32' && command === 'powershell.exe' && args.length === 4 &&
      args.slice(0, 3).join(' ') === '-NoProfile -NonInteractive -Command' && (
      /^\$p = Get-CimInstance Win32_Process -Filter 'ProcessId = \d+' -ErrorAction SilentlyContinue; if \(\$p\) \{ \$p\.(CreationDate\.ToFileTimeUtc\(\)|ParentProcessId) \}$/.test(args[3]) ||
      args[3] === 'Get-CimInstance Win32_Process | ForEach-Object { "$($_.ProcessId) $($_.ParentProcessId) $($_.CreationDate.ToFileTimeUtc())" }')) return args;
  if (command === 'ps' && (/^-o (lstart=|ppid=) -p \d+$/.test(args.join(' ')) ||
      args.join(' ') === '-axo pid=,ppid=,lstart=')) return args;
  if (command === 'pgrep' && /^-P \d+$/.test(args.join(' '))) return args;
  if (command === 'tasklist' && /^\/FO CSV \/NH \/FI PID eq \d+$/.test(args.join(' '))) return args;
  if (command === 'ps' && /^-o pid=,rss= -p \d+(,\d+)*$/.test(args.join(' '))) return args;
  // POSIX orphan cleanup reads the local process table; it never signals by name.
  if (command === 'ps' && /^(?:-U \d+|-A) -ww -o pid=,ppid=,args=$/.test(args.join(' '))) return args;
  // Linux shared-library preflight, only for the configured browser binary.
  if (process.platform === 'linux' && command === 'ldd' && args.length === 1 && browser && real(args[0]) === browser) return args;
  denied(path.basename(String(command)));
}
for (const key of ['spawn', 'spawnSync', 'execFile', 'execFileSync']) {
  const original = cp[key];
  cp[key] = function (command, args, options, ...rest) {
    return original.call(this, command, childArgs(command, args, options), options, ...rest);
  };
}
for (const key of ['exec', 'execSync', 'fork']) cp[key] = () => denied('child_process.' + key);
// Upstream's optional GPU memory query is fixed text. Never pass it to a shell.
cp.execSync = function (command, options) {
  if (command === 'nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits') {
    // No CUDA on this supported software path. An unavailable probe is expected.
    throw Error('GPU memory query disabled for offline software rendering');
  }
  return denied('child_process.execSync');
};
syncBuiltinESMExports();
