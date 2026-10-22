// Loaded before the pinned CLI. Deny external Node sockets/fetch, and force
// Chromium external traffic through an unused local proxy. Loopback is needed
// for HyperFrames' own HTTP server and Chrome DevTools, not internet access.
const fs = require('node:fs');
const net = require('node:net');
const cp = require('node:child_process');
const { syncBuiltinESMExports } = require('node:module');
// Confine upstream's homedir-based configuration without changing HOME or
// USERPROFILE. This affects only this child process and its imported modules.
if (process.env.ZING_HF_RUNTIME_HOME) require('node:os').homedir = () => process.env.ZING_HF_RUNTIME_HOME;
const local = host => ['localhost', '127.0.0.1', '::1', '[::1]'].includes(host);
function denied(host) {
  const message = `Offline render blocked external request: ${host}`;
  if (process.env.ZING_HF_NETWORK_LOG) fs.appendFileSync(process.env.ZING_HF_NETWORK_LOG, message + '\n');
  throw Error(message);
}
const connect = net.Socket.prototype.connect;
net.Socket.prototype.connect = function (...args) {
  const o = Array.isArray(args[0]) ? args[0][0] : args[0];
  const host = typeof o === 'object' ? o.host : typeof args[1] === 'string' ? args[1] : 'localhost';
  if (host && !local(host)) denied(host);
  return connect.apply(this, args);
};
const originalFetch = globalThis.fetch;
const dns = require('node:dns');
const lookup = dns.lookup;
dns.lookup = function (hostname, ...args) {
  if (!local(hostname)) denied(hostname);
  return lookup.call(this, hostname, ...args);
};
for (const key of Object.keys(dns)) {
  if (key.startsWith('resolve') && typeof dns[key] === 'function') dns[key] = host => denied(host);
}
for (const key of Object.keys(dns.promises)) {
  if ((key.startsWith('resolve') || key === 'lookup') && typeof dns.promises[key] === 'function') {
    const original = dns.promises[key];
    dns.promises[key] = (host, ...args) => {
      if (!local(host)) denied(host);
      return original.call(dns.promises, host, ...args);
    };
  }
}
globalThis.fetch = (input, options) => {
  const url = new URL(typeof input === 'string' || input instanceof URL ? input : input.url);
  if (!local(url.hostname)) denied(url.hostname);
  // No automatic redirects to a remote host.
  return originalFetch(input, { ...options, redirect: 'error' });
};
const spawn = cp.spawn;
cp.spawn = function (command, args, options) {
  if (/chrome[^/\\]*\.exe$|chrome-headless-shell$|chromium$/i.test(command)) {
    args = [...args, '--disable-background-networking', '--disable-component-update', '--disable-sync',
      '--proxy-server=http://127.0.0.1:9', '--proxy-bypass-list=localhost;127.0.0.1;[::1]',
      '--host-resolver-rules=MAP * ~NOTFOUND, EXCLUDE localhost'];
  }
  return spawn.call(this, command, args, options);
};
syncBuiltinESMExports();
