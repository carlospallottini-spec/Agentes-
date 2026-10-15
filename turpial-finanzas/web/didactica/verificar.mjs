import { medir, rng } from './motor.js';
import fs from 'node:fs';
const ses = JSON.parse(fs.readFileSync('/tmp/claude-0/sesiones.json', 'utf8'));
const real = medir(ses, (s) => s.niveles);
console.log(`REAL  js: ${real.aguanto}/${real.resueltos} = ${real.tasa.toFixed(1)}%   (python: 142/198 = 71.7%)`);
const n = Object.keys(ses[0].niveles).length;
const tasas = [];
for (let r = 0; r < 200; r++) {
  const az = rng(20261015 + r * 7919);
  const m = medir(ses, (s) => {
    const lo = s.prev.l - s.atr, hi = s.prev.h + s.atr, f = {};
    for (let j = 0; j < n; j++) f['azar' + j] = lo + az() * (hi - lo);
    return f;
  });
  if (m.resueltos > 0) tasas.push(m.tasa);
}
tasas.sort((a, b) => a - b);
const media = tasas.reduce((x, y) => x + y, 0) / tasas.length;
console.log(`AZAR  js: media ${media.toFixed(2)}%  p05 ${tasas[9].toFixed(1)}  p95 ${tasas[189].toFixed(1)}   (python: media 72.46, p05 67.61, p95 77.27)`);
