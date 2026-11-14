// Поселение v45 — экспериментальный сервер совместного поселения.
// Требуется Node.js LTS: https://nodejs.org/en/download/
// Запуск: node server.js
'use strict';
const http = require('node:http');
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const os = require('node:os');
const PORT = Number(process.env.PORT || 3000);
const HOST = '0.0.0.0';
const GAME_FILE = path.join(__dirname, 'Поселение v45.html');
const MAX_BODY = 32 * 1024 * 1024;
const players = new Map();
let hostId = null;
let started = false;
let sharedState = null;
let revision = 0;
const proposals = new Map();
let hostLastSeen = Date.now();

function playerList() {
  const now = Date.now();
  for (const [id, p] of players) if (id !== hostId && now - p.lastSeen > 60000) players.delete(id);
  return [...players.values()].map(p => ({ id: p.id, name: p.name, role: p.role }));
}
function cors(res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET,POST,OPTIONS');
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type');
  res.setHeader('Cache-Control', 'no-store');
}
function send(res, status, obj, contentType = 'application/json; charset=utf-8') {
  cors(res); res.writeHead(status, { 'Content-Type': contentType });
  res.end(contentType.startsWith('application/json') ? JSON.stringify(obj) : obj);
}
function readBody(req) {
  return new Promise((resolve, reject) => {
    let raw = '', size = 0;
    req.on('data', chunk => {
      size += chunk.length;
      if (size > MAX_BODY) { reject(new Error('request too large')); req.destroy(); return; }
      raw += chunk.toString('utf8');
    });
    req.on('end', () => {
      try { resolve(raw ? JSON.parse(raw) : {}); }
      catch (_) { reject(new Error('invalid json')); }
    });
    req.on('error', reject);
  });
}
function cleanName(value) {
  return String(value || 'Игрок').replace(/[<>\u0000-\u001f]/g, '').trim().slice(0, 24) || 'Игрок';
}
function makePlayer(name, role) {
  const id = crypto.randomUUID();
  const p = { id, name: cleanName(name), role, lastSeen: Date.now() };
  players.set(id, p); return p;
}
function heartbeat(id) {
  const p = players.get(String(id || ''));
  if (!p) return false;
  p.lastSeen = Date.now();
  if (p.id === hostId) hostLastSeen = p.lastSeen;
  return true;
}
const server = http.createServer(async (req, res) => {
  const url = new URL(req.url, `http://${req.headers.host || 'localhost'}`);
  const pathname = decodeURIComponent(url.pathname);
  if (req.method === 'OPTIONS') { cors(res); res.writeHead(204); return res.end(); }

  if (req.method === 'GET' && (pathname === '/' || pathname === '/index.html' || pathname === '/Поселение v45.html')) {
    if (!fs.existsSync(GAME_FILE)) return send(res, 404, 'Не найден файл «Поселение v45.html». Положите его рядом с server.js.', 'text/plain; charset=utf-8');
    cors(res); res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    return fs.createReadStream(GAME_FILE).pipe(res);
  }
  if (req.method === 'GET' && pathname === '/api/status') {
    return send(res, 200, { ok: true, hostOnline: !!hostId, started, revision, players: playerList() });
  }
  if (req.method === 'GET' && pathname === '/api/state') {
    heartbeat(url.searchParams.get('id'));
    const since = Number(url.searchParams.get('since') || 0);
    return send(res, 200, { ok: true, hostOnline: !!hostId, started, revision,
      state: sharedState && revision > since ? sharedState : null, players: playerList(), hostId });
  }
  if (req.method === 'GET' && pathname === '/api/pending') {
    const id = url.searchParams.get('id'); heartbeat(id);
    if (!hostId || id !== hostId) return send(res, 403, { ok: false, error: 'host only' });
    const pending = [...proposals.values()]; proposals.clear();
    return send(res, 200, { ok: true, proposals: pending, players: playerList() });
  }
  if (req.method !== 'POST') return send(res, 404, { ok: false, error: 'not found' });

  let body;
  try { body = await readBody(req); }
  catch (err) { return send(res, err.message === 'request too large' ? 413 : 400, { ok: false, error: err.message }); }

  if (pathname === '/api/host') {
    if (hostId && Date.now() - hostLastSeen < 45000) return send(res, 409, { ok: false, error: 'Уже есть активный хост' });
    players.clear(); proposals.clear(); sharedState = null; revision = 0; started = false;
    const p = makePlayer(body.name, 'host'); hostId = p.id; hostLastSeen = Date.now();
    return send(res, 200, { ok: true, id: p.id, role: 'host', revision, players: playerList() });
  }
  if (pathname === '/api/join') {
    if (!hostId) return send(res, 409, { ok: false, error: 'Хост ещё не запустил сервер' });
    const p = makePlayer(body.name, 'guest');
    return send(res, 200, { ok: true, id: p.id, role: 'guest', started, revision, state: sharedState, players: playerList() });
  }
  if (pathname === '/api/heartbeat' || pathname === '/api/leave') {
    const id = String(body.id || '');
    if (pathname === '/api/leave') {
      if (id === hostId) { hostId = null; started = false; sharedState = null; revision = 0; proposals.clear(); players.clear(); }
      else { players.delete(id); proposals.delete(id); }
      return send(res, 200, { ok: true });
    }
    return send(res, 200, { ok: heartbeat(id), players: playerList() });
  }
  if (pathname === '/api/state') {
    const id = String(body.id || '');
    if (!hostId || id !== hostId || !players.has(id)) return send(res, 403, { ok: false, error: 'host only' });
    if (!body.save || typeof body.save !== 'object' || body.save.version !== 13 || !Array.isArray(body.save.terrain))
      return send(res, 400, { ok: false, error: 'invalid save snapshot' });
    heartbeat(id); sharedState = body.save; started = true; revision++;
    return send(res, 200, { ok: true, revision });
  }
  if (pathname === '/api/propose') {
    const id = String(body.id || '');
    if (!players.has(id) || id === hostId) return send(res, 403, { ok: false, error: 'player not connected' });
    if (!body.save || typeof body.save !== 'object' || body.save.version !== 13 || !Array.isArray(body.save.terrain))
      return send(res, 400, { ok: false, error: 'invalid save snapshot' });
    heartbeat(id);
    // Последнее действие каждого гостя заменяет предыдущее, чтобы очередь не разрасталась.
    proposals.set(id, { id, name: players.get(id).name, baseRevision: Number(body.baseRevision || 0), save: body.save, sentAt: Date.now() });
    return send(res, 200, { ok: true });
  }
  return send(res, 404, { ok: false, error: 'not found' });
});
server.on('error', err => {
  console.error('Не удалось запустить сервер:', err.message);
  if (err.code === 'EADDRINUSE') console.error(`Порт ${PORT} уже занят. Закройте другой сервер или запустите: PORT=3001 node server.js`);
  process.exitCode = 1;
});
server.listen(PORT, HOST, () => {
  console.log(`Поселение v45: сервер запущен на http://localhost:${PORT}`);
  const addresses = Object.values(os.networkInterfaces()).flatMap(items => items || [])
    .filter(item => item.family === 'IPv4' && !item.internal).map(item => item.address);
  for (const address of [...new Set(addresses)]) console.log(`Для игроков в вашей сети: http://${address}:${PORT}`);
  console.log('Экспериментальный сервер без паролей: используйте только в доверенной сети.');
});
process.on('SIGINT', () => { console.log('\nСервер остановлен.'); server.close(() => process.exit(0)); });
