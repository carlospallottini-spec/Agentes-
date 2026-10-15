// Puerto exacto de quant/toques.py::_recorrer_sesion. Si esto se desvía, la app miente.
export const TOL = 0.10, MARGEN = 0.25, MAX_BARRAS = 24;

export function recorrerSesion(barras, niveles, atr, acc, traza) {
  const tol = TOL * atr, margen = MARGEN * atr;
  const estado = {};
  for (let idx = 0; idx < barras.length; idx++) {
    const [, o, alto, bajo] = barras[idx];
    for (const nombre of Object.keys(niveles)) {
      const precio = niveles[nombre];
      const a = (acc[nombre] ||= { toques: 0, aguanto: 0, rompio: 0, ambiguos: 0, sin_resolver: 0 });
      const st = estado[nombre];
      const toca = bajo <= precio + tol && alto >= precio - tol;

      if (st && st.espera) { if (!toca) delete estado[nombre]; continue; }

      if (!st) {
        if (toca) {
          const anterior = idx > 0 ? barras[idx - 1][4] : o;
          estado[nombre] = { dir: anterior < precio ? 'abajo' : 'arriba', i: idx };
          a.toques++;
          if (traza) traza.push({ nombre, tipo: 'toque', idx, dir: estado[nombre].dir });
        }
        continue;
      }
      if (idx <= st.i) continue;

      const rompeArriba = alto >= precio + margen;
      const rompeAbajo = bajo <= precio - margen;
      let res = null;
      if (rompeArriba && rompeAbajo) res = 'ambiguos';
      else if (st.dir === 'abajo') res = rompeArriba ? 'rompio' : (rompeAbajo ? 'aguanto' : null);
      else res = rompeAbajo ? 'rompio' : (rompeArriba ? 'aguanto' : null);

      if (res === null && idx - st.i >= MAX_BARRAS) res = 'sin_resolver';
      if (res) {
        a[res]++;
        if (traza) traza.push({ nombre, tipo: res, idx, desde: st.i });
        estado[nombre] = { espera: true };
      }
    }
  }
  for (const nombre of Object.keys(estado)) {
    if (!estado[nombre].espera) acc[nombre].sin_resolver++;
  }
}

export function medir(sesiones, elegirNiveles) {
  const acc = {};
  for (const s of sesiones) recorrerSesion(s.barras, elegirNiveles(s), s.atr, acc);
  let res = 0, ag = 0;
  for (const k of Object.keys(acc)) { res += acc[k].aguanto + acc[k].rompio; ag += acc[k].aguanto; }
  return { acc, resueltos: res, aguanto: ag, tasa: res ? (100 * ag) / res : null };
}

// Mismo generador congruencial que el Pine, para que las corridas sean reproducibles.
export function rng(semilla) {
  let s = semilla >>> 0;
  return () => { s = (Math.imul(s, 1103515245) + 12345) >>> 0; return (s % 2147483648) / 2147483648; };
}
