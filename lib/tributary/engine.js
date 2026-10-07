/* engine.js — движок грузовых площадей для HTML-схемы.
 * Порт один к одному модулей lib/tributary (supports, trib, classify, punching, vector, pipeline):
 * схема сама пересчитывает зоны, когда в ней отключают стены/колонны/балки или меняют параметры.
 * Совпадение с Python проверяет tests/test_engine_parity.py (node). Правишь Python — правь и здесь.
 * Всё в мм. Работает в браузере (window.TribEngine) и в node (module.exports).
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory();
  else root.TribEngine = factory();
}(typeof self !== 'undefined' ? self : this, function () {
'use strict';

// ------------------------------------------------------------------ geom
function sub(a, b) { return [a[0] - b[0], a[1] - b[1]]; }
function dot(a, b) { return a[0] * b[0] + a[1] * b[1]; }
function cross(a, b) { return a[0] * b[1] - a[1] * b[0]; }
function len(a) { return Math.sqrt(a[0] * a[0] + a[1] * a[1]); }
function unit(a) { var L = len(a); return L > 1e-9 ? [a[0] / L, a[1] / L] : [1.0, 0.0]; }
function dist(a, b) { return len(sub(a, b)); }
function segParam(p, a, u) { var d = sub(p, a); return [dot(d, u), Math.abs(cross(u, d))]; }
function distToSeg(p, a, u, L) {
  var d = sub(p, a), s = dot(d, u);
  if (s < 0.0) s = 0.0; else if (s > L) s = L;
  return len([d[0] - s * u[0], d[1] - s * u[1]]);
}
function lineInt(p1, u1, p2, u2) {
  var den = cross(u1, u2);
  if (Math.abs(den) < 1e-9) return null;
  var t = cross(sub(p2, p1), u2) / den;
  return [p1[0] + t * u1[0], p1[1] + t * u1[1]];
}
function angleDeg(u1, u2) { var c = Math.max(-1.0, Math.min(1.0, dot(u1, u2))); return Math.acos(c) * 180 / Math.PI; }
function polyArea(pts) {
  var a = 0.0, n = pts.length;
  for (var i = 0; i < n; i++) { var p = pts[i], q = pts[(i + 1) % n]; a += p[0] * q[1] - q[0] * p[1]; }
  return Math.abs(a) / 2.0;
}
function rectDist(p, c, u, hx, hy) {
  var dx = p[0] - c[0], dy = p[1] - c[1];
  var a = Math.abs(dx * u[0] + dy * u[1]) - hx, b = Math.abs(-dx * u[1] + dy * u[0]) - hy;
  a = a > 0.0 ? a : 0.0; b = b > 0.0 ? b : 0.0;
  return Math.sqrt(a * a + b * b);
}
function pyRound(x, nd) {             // round() CPython 3: половина — к чётному
  var m = Math.pow(10, nd || 0), v = x * m, f = Math.floor(v), r = v - f;
  var out = r > 0.5 ? f + 1 : r < 0.5 ? f : (f % 2 === 0 ? f : f + 1);
  if (Math.abs(r - 0.5) > 1e-9 && Math.abs(r - 0.5) < 1e-12) out = Math.round(v);
  return out / m;
}
function dM(h, p) { return Math.max(h - p.c_nom - p.bar_d, 0.3 * h); }

// ------------------------------------------------------------------ heap (кортежи [d, idx, li])
function Heap() { this.a = []; }
function less(x, y) { return x[0] < y[0] || (x[0] === y[0] && (x[1] < y[1] || (x[1] === y[1] && x[2] < y[2]))); }
Heap.prototype.push = function (x) {
  var a = this.a, i = a.length; a.push(x);
  while (i > 0) { var p = (i - 1) >> 1; if (less(a[i], a[p])) { var t = a[i]; a[i] = a[p]; a[p] = t; i = p; } else break; }
};
Heap.prototype.pop = function () {
  var a = this.a, top = a[0], last = a.pop();
  if (a.length) {
    a[0] = last; var i = 0, n = a.length;
    for (;;) {
      var l = 2 * i + 1, r = l + 1, m = i;
      if (l < n && less(a[l], a[m])) m = l;
      if (r < n && less(a[r], a[m])) m = r;
      if (m === i) break;
      var t = a[i]; a[i] = a[m]; a[m] = t; i = m;
    }
  }
  return top;
};

// ------------------------------------------------------------------ trib.Grid
var OUT = 0, SLAB = 1, HOLE = 2;
function spans(loops, y) {
  var xs = [];
  for (var l = 0; l < loops.length; l++) {
    var pts = loops[l], n = pts.length;
    for (var a = 0; a < n; a++) {
      var x1 = pts[a][0], y1 = pts[a][1], x2 = pts[(a + 1) % n][0], y2 = pts[(a + 1) % n][1];
      if ((y1 <= y && y < y2) || (y2 <= y && y < y1)) xs.push(x1 + (y - y1) * (x2 - x1) / (y2 - y1));
    }
  }
  xs.sort(function (p, q) { return p - q; });
  var out = [];
  for (var k = 0; k + 1 < xs.length; k += 2) out.push([xs[k], xs[k + 1]]);
  return out;
}
function Grid(slabs, step) {
  var s = this.s = +step, xs = [], ys = [], g = this;
  slabs.forEach(function (sl) { sl.outer.forEach(function (q) { xs.push(q[0]); ys.push(q[1]); }); });
  if (!xs.length) throw new Error('no slab outlines');
  var mnx = Math.min.apply(null, xs), mxx = Math.max.apply(null, xs), mny = Math.min.apply(null, ys), mxy = Math.max.apply(null, ys);
  this.x0 = mnx - s; this.y0 = mny - s;
  this.nx = Math.ceil((mxx - this.x0) / s) + 2;
  this.ny = Math.ceil((mxy - this.y0) / s) + 2;
  var N = this.nx * this.ny;
  this.kind = new Uint8Array(N);
  this.slab = new Int32Array(N).fill(-1);
  this.h = slabs.map(function (sl) { return +sl.h; });
  var polys = [];
  slabs.forEach(function (sl, k) {
    g._fill(k, sl);
    var a = polyArea(sl.outer); (sl.holes || []).forEach(function (hl) { a -= polyArea(hl); });
    polys.push(Math.max(a, 0.0));
  });
  this.area_poly = polys.reduce(function (p, q) { return p + q; }, 0);
  var cnt = new Array(slabs.length).fill(0);
  for (var i = 0; i < N; i++) if (this.slab[i] >= 0) cnt[this.slab[i]]++;
  this.weight = []; this.overlaps = [];
  for (var k = 0; k < slabs.length; k++) {
    var f = cnt[k] ? polys[k] / (cnt[k] * s * s) : 1.0;
    if (!(f >= 0.8 && f <= 1.25)) { if (cnt[k]) this.overlaps.push(slabs[k].id); f = 1.0; }
    this.weight.push(f);
  }
  this._closeGaps();
}
Grid.prototype.cy = function (j) { return this.y0 + (j + 0.5) * this.s; };
Grid.prototype._irange = function (xa, xb) {
  var i0 = Math.ceil((xa - this.x0) / this.s - 0.5), i1 = Math.floor((xb - this.x0) / this.s - 0.5);
  return [Math.max(i0, 0), Math.min(i1, this.nx - 1)];
};
Grid.prototype._fill = function (k, sl) {
  var outer = sl.outer, holes = sl.holes || [], ys = outer.map(function (q) { return q[1]; });
  var j0 = Math.max(Math.floor((Math.min.apply(null, ys) - this.y0) / this.s) - 1, 0);
  var j1 = Math.min(Math.floor((Math.max.apply(null, ys) - this.y0) / this.s) + 1, this.ny - 1);
  var nx = this.nx, all = [outer].concat(holes);
  for (var j = j0; j <= j1; j++) {
    var y = this.cy(j), sp = spans(all, y);
    for (var a = 0; a < sp.length; a++) {
      var r = this._irange(sp[a][0], sp[a][1]);
      for (var i = r[0]; i <= r[1]; i++) {
        var idx = j * nx + i;
        if (this.kind[idx] !== SLAB) { this.kind[idx] = SLAB; this.slab[idx] = k; }
      }
    }
    if (holes.length) {
      var hs = spans(holes, y);
      for (var b = 0; b < hs.length; b++) {
        var r2 = this._irange(hs[b][0], hs[b][1]);
        for (var i2 = r2[0]; i2 <= r2[1]; i2++) { var id2 = j * nx + i2; if (this.kind[id2] === OUT) this.kind[id2] = HOLE; }
      }
    }
  }
};
Grid.prototype._closeGaps = function () {
  var nx = this.nx, ny = this.ny, kind = this.kind, fix = [];
  for (var j = 1; j < ny - 1; j++) for (var i = 1; i < nx - 1; i++) {
    var idx = j * nx + i;
    if (kind[idx] !== OUT) continue;
    if (kind[idx - 1] === SLAB && kind[idx + 1] === SLAB) fix.push([idx, this.slab[idx - 1]]);
    else if (kind[idx - nx] === SLAB && kind[idx + nx] === SLAB) fix.push([idx, this.slab[idx - nx]]);
  }
  for (var f = 0; f < fix.length; f++) { kind[fix[f][0]] = SLAB; this.slab[fix[f][0]] = fix[f][1]; }
  this.closed_cells = fix.length;
};
Grid.prototype.index = function (x, y) {
  var i = Math.floor((x - this.x0) / this.s), j = Math.floor((y - this.y0) / this.s);
  if (i < 0 || j < 0 || i >= this.nx || j >= this.ny) return -1;
  return j * this.nx + i;
};
Grid.prototype.kindAt = function (x, y) { var idx = this.index(x, y); return idx < 0 ? OUT : this.kind[idx]; };
Grid.prototype.hNear = function (x, y, r) {
  r = r || 1500.0;
  var idx = this.index(x, y);
  if (idx >= 0 && this.slab[idx] >= 0) return this.h[this.slab[idx]];
  var n = Math.floor(r / this.s), i0 = Math.floor((x - this.x0) / this.s), j0 = Math.floor((y - this.y0) / this.s);
  var best = null, bh = null;
  for (var j = Math.max(j0 - n, 0); j <= Math.min(j0 + n, this.ny - 1); j++)
    for (var i = Math.max(i0 - n, 0); i <= Math.min(i0 + n, this.nx - 1); i++) {
      var k = this.slab[j * this.nx + i];
      if (k >= 0) { var d = (i - i0) * (i - i0) + (j - j0) * (j - j0); if (best === null || d < best) { best = d; bh = this.h[k]; } }
    }
  return bh !== null ? bh : Math.max.apply(null, this.h);
};
Grid.prototype.slabArea = function () {
  var t = 0; for (var i = 0; i < this.slab.length; i++) if (this.slab[i] >= 0) t += this.weight[this.slab[i]];
  return t * this.s * this.s;
};

// ------------------------------------------------------------------ trib.assign
var SEG = 0, RECT = 1, ROUND = 2, CODE = {seg: SEG, rect: RECT, round: ROUND};
function compile(src) { return [CODE[src[0]], +src[1], +src[2], +src[3], +src[4], +src[5], +src[6]]; }
function sdist(c, x, y) {
  var dx = x - c[1], dy = y - c[2], d;
  if (c[0] === SEG) {
    // стена/балка — прямоугольник с ПЛОСКИМИ торцами (не капсула): иначе торец толстой стены,
    // упёртой в тонкую, вылезал на (t1 − t2)/2 за её грань и забирал площадь по ту сторону
    var s = dx * c[3] + dy * c[4], q = Math.abs(dy * c[3] - dx * c[4]) - c[6];
    var ea = s < 0.0 ? -s : (s > c[5] ? s - c[5] : 0.0), eb = q > 0.0 ? q : 0.0;
    d = Math.sqrt(ea * ea + eb * eb);
  } else if (c[0] === RECT) {
    var a = Math.abs(dx * c[3] + dy * c[4]) - c[5], b = Math.abs(dy * c[3] - dx * c[4]) - c[6];
    a = a > 0.0 ? a : 0.0; b = b > 0.0 ? b : 0.0;
    d = Math.sqrt(a * a + b * b);
  } else d = Math.sqrt(dx * dx + dy * dy) - c[5];
  return d > 0.0 ? d : 0.0;
}
function sbbox(c) {
  if (c[0] === SEG) {
    var x2 = c[1] + c[3] * c[5], y2 = c[2] + c[4] * c[5], r = c[6];
    return [Math.min(c[1], x2) - r, Math.min(c[2], y2) - r, Math.max(c[1], x2) + r, Math.max(c[2], y2) + r];
  }
  var rr = c[5] + c[6];
  return [c[1] - rr, c[2] - rr, c[1] + rr, c[2] + rr];
}
var SEED_TOL = 50.0;
var NBS = [[-1, 0],[1, 0], [0, -1], [0, 1], [-1, -1], [1, -1], [-1, 1], [1, 1]];
function assign(g, sources) {
  var comp = sources.map(compile), nx = g.nx, ny = g.ny, s = g.s, kind = g.kind, N = nx * ny;
  var distA = new Float64Array(N).fill(Infinity), label = new Int32Array(N).fill(-1), heap = new Heap();
  var seedR = s + SEED_TOL, x0 = g.x0, y0 = g.y0;     // см. trib.assign: стена снаружи контура плиты
  for (var li = 0; li < comp.length; li++) {
    var c = comp[li], bb = sbbox(c);
    var i0 = Math.max(Math.floor((bb[0] - x0) / s) - 1, 0), i1 = Math.min(Math.floor((bb[2] - x0) / s) + 1, nx - 1);
    var j0 = Math.max(Math.floor((bb[1] - y0) / s) - 1, 0), j1 = Math.min(Math.floor((bb[3] - y0) / s) + 1, ny - 1);
    for (var j = j0; j <= j1; j++) {
      var y = y0 + (j + 0.5) * s;
      for (var i = i0; i <= i1; i++) {
        var idx = j * nx + i;
        if (kind[idx] !== SLAB) continue;
        var d = sdist(c, x0 + (i + 0.5) * s, y);
        if (d <= seedR && d < distA[idx]) { distA[idx] = d; label[idx] = li; heap.push([d, idx, li]); }
      }
    }
  }
  while (heap.a.length) {
    var t = heap.pop(), dd = t[0], id = t[1], lb = t[2];
    if (label[id] !== lb || dd > distA[id]) continue;
    var cc = comp[lb], ci = id % nx, cj = (id - ci) / nx;
    for (var q = 0; q < 8; q++) {
      var di = NBS[q][0], dj = NBS[q][1], ii = ci + di, jj = cj + dj;
      if (ii < 0 || jj < 0 || ii >= nx || jj >= ny) continue;
      var k = jj * nx + ii;
      if (kind[k] !== SLAB) continue;
      if (di && dj && (kind[cj * nx + ii] !== SLAB || kind[jj * nx + ci] !== SLAB)) continue;
      var nd = sdist(cc, x0 + (ii + 0.5) * s, y0 + (jj + 0.5) * s);
      if (nd < dd - 1e-6) continue;
      if (nd < distA[k] - 1e-6) { distA[k] = nd; label[k] = lb; heap.push([nd, k, lb]); }
    }
  }
  fillHidden(g, label, distA);
  return {label: label, dist: distA};
}
function fillHidden(g, label, distA) {
  var nx = g.nx, ny = g.ny, s = g.s, kind = g.kind, N = nx * ny, hidden = new Uint8Array(N), any = false;
  for (var i = 0; i < N; i++) if (kind[i] === SLAB && label[i] < 0) { hidden[i] = 1; any = true; }
  if (!any) return;
  var heap = new Heap();
  // порядок как в Python: обход множества hidden (там — set, здесь — по возрастанию индекса);
  // на результат не влияет: у одинаковых кортежей (d, idx, li) один и тот же исход
  for (var idx = 0; idx < N; idx++) {
    if (!hidden[idx]) continue;
    var ci = idx % nx, cj = (idx - ci) / nx;
    for (var q = 0; q < 8; q++) {
      var ii = ci + NBS[q][0], jj = cj + NBS[q][1];
      if (ii >= 0 && ii < nx && jj >= 0 && jj < ny) {
        var k = jj * nx + ii;
        if (label[k] >= 0 && !hidden[k]) heap.push([distA[k], k, label[k]]);
      }
    }
  }
  var diag = s * Math.SQRT2;
  while (heap.a.length) {
    var t = heap.pop(), d = t[0], id = t[1], li = t[2];
    if (label[id] !== li || d > distA[id]) continue;
    var ai = id % nx, aj = (id - ai) / nx;
    for (var q2 = 0; q2 < 8; q2++) {
      var di = NBS[q2][0], dj = NBS[q2][1], i2 = ai + di, j2 = aj + dj;
      if (i2 < 0 || j2 < 0 || i2 >= nx || j2 >= ny) continue;
      var k2 = j2 * nx + i2;
      if (!hidden[k2]) continue;
      if (di && dj && (kind[aj * nx + i2] !== SLAB || kind[j2 * nx + ai] !== SLAB)) continue;
      var nd = d + (di && dj ? diag : s);
      if (nd < distA[k2] - 1e-6) { distA[k2] = nd; label[k2] = li; heap.push([nd, k2, li]); }
    }
  }
}
function areasBySlab(g, label, nSrc) {
  var out = [], none = new Map(), a = g.s * g.s;
  for (var i = 0; i < nSrc; i++) out.push(new Map());
  for (var idx = 0; idx < label.length; idx++) {
    if (g.kind[idx] !== SLAB) continue;
    var k = g.slab[idx], li = label[idx], d = li < 0 ? none : out[li];
    d.set(k, (d.get(k) || 0.0) + g.weight[k] * a);
  }
  return {bySrc: out, none: none};
}

// ------------------------------------------------------------------ supports
var KINDS_NODE = ['wall_L', 'wall_end'];
var BEAM_END_TOL = 100.0;
function Wall(i, w) {
  this.i = i; this.id = w.id; this.link = w.link || ''; this.name = w.name || '';
  this.a = [+w.p0[0], +w.p0[1]]; this.b = [+w.p1[0], +w.p1[1]]; this.t = +w.t;
  this.L = dist(this.a, this.b); this.u = unit(sub(this.b, this.a));
  this.lo = [Math.min(this.a[0], this.b[0]), Math.min(this.a[1], this.b[1])];
  this.hi = [Math.max(this.a[0], this.b[0]), Math.max(this.a[1], this.b[1])];
}
Wall.prototype.end = function (e) { return e === 0 ? this.a : this.b; };
Wall.prototype.into = function (e) { return e === 0 ? this.u : [-this.u[0], -this.u[1]]; };
Wall.prototype.pt = function (s) { return [this.a[0] + s * this.u[0], this.a[1] + s * this.u[1]]; };
Wall.prototype.sOf = function (p) { var s = dot(sub(p, this.a), this.u); return Math.min(Math.max(s, 0.0), this.L); };
Wall.prototype.nearBox = function (p, r) {
  return this.lo[0] - r <= p[0] && p[0] <= this.hi[0] + r && this.lo[1] - r <= p[1] && p[1] <= this.hi[1] + r;
};
function UF(n) { this.p = []; for (var i = 0; i < n; i++) this.p.push(i); }
UF.prototype.find = function (x) { while (this.p[x] !== x) { this.p[x] = this.p[this.p[x]]; x = this.p[x]; } return x; };
UF.prototype.union = function (a, b) { var ra = this.find(a), rb = this.find(b); if (ra !== rb) this.p[rb] = ra; };

function columnPoint(c) {
  var u = unit([+(c.ux != null ? c.ux : 1.0), +(c.uy != null ? c.uy : 0.0)]);
  var x = +c.x, y = +c.y, b = +c.b, h = +c.h;
  var src = c.shape === 'round' ? ['round', x, y, u[0], u[1], b / 2.0, b / 2.0] : ['rect', x, y, u[0], u[1], b / 2.0, h / 2.0];
  return {kind: 'column', x: x, y: y, ids: [c.id], links: [c.link || ''], names: [c.name || ''], flags: [],
    dims: {shape: c.shape || 'rect', b: b, h: h, ux: u[0], uy: u[1]}, src: [src]};
}
function colContains(col, p, r) {
  var s = col.src[0];
  if (s[0] === 'round') return dist(p, [s[1], s[2]]) - s[5] <= r;
  return rectDist(p, [s[1], s[2]], [s[3], s[4]], s[5], s[6]) <= r;
}
function slabAlong(slabAt, pt, d, tmax, dmAt) {
  var dm = dmAt(pt[0], pt[1]), hits = 0;
  [0.5, 1.0, 1.5].forEach(function (f) {
    var r = tmax * 0.75 + f * dm;
    if (slabAt(pt[0] + d[0] * r, pt[1] + d[1] * r)) hits++;
  });
  return hits >= 2;
}
function supportedBeams(beams, W, cols, notes, force) {
  var cand = [];
  beams.forEach(function (b) {
    var a = [+b.p0[0], +b.p0[1]], c = [+b.p1[0], +b.p1[1]], L = dist(a, c);
    if (L < 1.0) return;
    cand.push({b: b, geo: [a, unit(sub(c, a)), L, +(b.b || 200.0)], ends: [a, c]});
  });
  function onFixed(P) {
    for (var i = 0; i < W.length; i++) { var w = W[i]; if (distToSeg(P, w.a, w.u, w.L) <= w.t / 2.0 + BEAM_END_TOL) return true; }
    for (var k = 0; k < cols.length; k++) if (colContains(cols[k], P, BEAM_END_TOL)) return true;
    return false;
  }
  var ok = cand.map(function (bm) { return force && force[bm.b.id] === true; });
  var fixed = cand.map(function (bm) { return bm.ends.map(onFixed); });
  var changed = true;
  while (changed) {
    changed = false;
    for (var i = 0; i < cand.length; i++) {
      if (ok[i]) continue;
      var allOk = true;
      for (var e = 0; e < 2; e++) {
        var P = cand[i].ends[e], good = fixed[i][e];
        if (!good) {
          for (var k = 0; k < cand.length; k++) {
            if (k !== i && ok[k]) {
              var o = cand[k].geo;
              if (distToSeg(P, o[0], o[1], o[2]) <= o[3] / 2.0 + BEAM_END_TOL) { good = true; break; }
            }
          }
        }
        if (!good) allOk = false;
      }
      if (allOk) { ok[i] = true; changed = true; }
    }
  }
  var rejected = cand.filter(function (bm, i) { return !ok[i]; }).map(function (bm) { return bm.b.id; });
  if (rejected.length) notes.push('beams not supported at both ends are not used as supports (' + rejected.length + '): ' +
    rejected.slice(0, 20).join(', '));
  return cand.filter(function (bm, i) { return ok[i]; });
}

function build(walls, columns, beams, p, dmAt, slabAt, beamForce) {
  var tol = p.node_tol, minAng = p.min_angle, notes = [];
  var points = columns.map(columnPoint), cols = points.slice();
  var W = walls.map(function (w, i) { return new Wall(i, w); }).filter(function (w) { return w.L > 1.0 && w.t > 1.0; });
  W.forEach(function (w, i) { w.i = i; });
  var n = W.length, uf = new UF(2 * n), mids = new Map(), colOf = new Map();
  var hasContact = new Array(2 * n).fill(false), midsOn = [];
  for (var z = 0; z < n; z++) midsOn.push([]);

  W.forEach(function (wi) {
    for (var e = 0; e < 2; e++) {
      var h = 2 * wi.i + e, P = wi.end(e);
      for (var ci = 0; ci < cols.length; ci++) {
        if (colContains(cols[ci], P, wi.t / 2.0 + tol)) { colOf.set(h, ci); hasContact[h] = true; break; }
      }
      for (var jx = 0; jx < W.length; jx++) {
        var wj = W[jx];
        if (wj.i === wi.i) continue;
        var reach = (wi.t + wj.t) / 2.0 + tol;
        if (!wj.nearBox(P, reach)) continue;
        if (distToSeg(P, wj.a, wj.u, wj.L) > reach) continue;
        var sp = segParam(P, wj.a, wj.u), s = sp[0], perp = sp[1];
        var ang = angleDeg(wi.u, wj.u), parallel = ang < minAng || ang > 180.0 - minAng;
        if (parallel && perp > Math.max(wi.t, wj.t) / 2.0 + tol) continue;
        if (s <= reach) { uf.union(h, 2 * wj.i); hasContact[h] = hasContact[2 * wj.i] = true; }
        else if (s >= wj.L - reach) { uf.union(h, 2 * wj.i + 1); hasContact[h] = hasContact[2 * wj.i + 1] = true; }
        else if (parallel) notes.push('walls ' + wi.id + ' and ' + wj.id + ': parallel and overlapping');
        else {
          if (!mids.has(h)) mids.set(h, []);
          mids.get(h).push([wj.i, s]); midsOn[wj.i].push(s); hasContact[h] = true;
        }
      }
    }
  });

  var pylon = new Array(n).fill(false);
  W.forEach(function (w) {
    if (!hasContact[2 * w.i] && !hasContact[2 * w.i + 1] && !midsOn[w.i].length && w.L <= p.pylon_ratio * w.t) {
      pylon[w.i] = true;
      var c = w.pt(w.L / 2.0);
      points.push({kind: 'pylon', x: c[0], y: c[1], ids: [w.id], links: [w.link], names: [w.name], flags: [],
        dims: {shape: 'rect', b: w.L, h: w.t, ux: w.u[0], uy: w.u[1]},
        src: [['rect', c[0], c[1], w.u[0], w.u[1], w.L / 2.0, w.t / 2.0]]});
    }
  });

  var groups = new Map();
  W.forEach(function (w) {
    if (pylon[w.i]) return;
    for (var e = 0; e < 2; e++) {
      var h = 2 * w.i + e, r = uf.find(h);
      if (!groups.has(r)) groups.set(r, []);
      groups.get(r).push(h);
    }
  });
  var nodes = [];
  groups.forEach(function (hs) {
    var here = new Set(hs.map(function (h) { return (h - h % 2) / 2; })), legs = [], lines = [], ends = [];
    hs.forEach(function (h) {
      var w = W[(h - h % 2) / 2], e = h % 2;
      legs.push([w.i, w.into(e)]); lines.push([w.end(e), w.u]); ends.push(w.end(e));
    });
    var passing = new Map();
    hs.forEach(function (h) {
      (mids.get(h) || []).forEach(function (js) {
        if (!here.has(js[0])) { if (!passing.has(js[0])) passing.set(js[0], []); passing.get(js[0]).push(js[1]); }
      });
    });
    passing.forEach(function (ss, j) {
      var w = W[j];
      legs.push([j, w.u]); legs.push([j, [-w.u[0], -w.u[1]]]); lines.push([w.a, w.u]);
    });
    nodes.push({legs: legs, lines: lines, ends: ends,
      col: hs.filter(function (h) { return colOf.has(h); }).map(function (h) { return colOf.get(h); }), flags: []});
  });

  for (var ia = 0; ia < W.length; ia++) for (var ib = 0; ib < W.length; ib++) {
    var wi = W[ia], wj = W[ib];
    if (wj.i <= wi.i || pylon[wi.i] || pylon[wj.i]) continue;
    var ang2 = angleDeg(wi.u, wj.u);
    if (ang2 < minAng || ang2 > 180.0 - minAng) continue;
    var x = lineInt(wi.a, wi.u, wj.a, wj.u);
    if (x === null) continue;
    var si = dot(sub(x, wi.a), wi.u), sj = dot(sub(x, wj.a), wj.u), ri = wj.t + tol, rj = wi.t + tol;
    if (ri < si && si < wi.L - ri && rj < sj && sj < wj.L - rj) {
      nodes.push({legs: [[wi.i, wi.u], [wi.i, [-wi.u[0], -wi.u[1]]], [wj.i, wj.u], [wj.i, [-wj.u[0], -wj.u[1]]]],
        lines: [[wi.a, wi.u], [wj.a, wj.u]], ends: [x], col: [], flags: []});
    }
  }

  nodes.forEach(function (nd) {
    var pt = null, ln = nd.lines;
    outer: for (var a = 0; a < ln.length; a++) for (var b = a + 1; b < ln.length; b++) {
      var ang = angleDeg(ln[a][1], ln[b][1]);
      if (minAng <= ang && ang <= 180.0 - minAng) { pt = lineInt(ln[a][0], ln[a][1], ln[b][0], ln[b][1]); break outer; }
    }
    var cx = 0, cy = 0;
    nd.ends.forEach(function (q) { cx += q[0]; cy += q[1]; });
    cx /= nd.ends.length; cy /= nd.ends.length;
    if (pt === null || dist(pt, [cx, cy]) > 1000.0) pt = [cx, cy];
    nd.pt = pt;
    var k = nd.legs.length;
    if (nd.col.length) nd.kind = 'col_join';
    else if (k === 1) nd.kind = 'wall_end';
    else if (k === 2) { var an = angleDeg(nd.legs[0][1], nd.legs[1][1]); nd.kind = an > 180.0 - minAng ? 'cont' : 'wall_L'; nd.angle = an; }
    else if (k === 3) nd.kind = 'wall_T';
    else nd.kind = 'wall_X';
  });
  nodes.forEach(function (nd) {
    nd.col.forEach(function (ci) { if (cols[ci].flags.indexOf('wall attached') < 0) cols[ci].flags.push('wall attached'); });
    if (!slabAt) return;
    var tmax = Math.max.apply(null, nd.legs.map(function (l) { return W[l[0]].t; }));
    if (nd.kind === 'wall_L') {
      var d1 = nd.legs[0][1], d2 = nd.legs[1][1], out = unit([-(d1[0] + d2[0]), -(d1[1] + d2[1])]);
      if (!slabAlong(slabAt, nd.pt, out, tmax, dmAt)) nd.kind = 'wall_L_in';
    } else if (nd.kind === 'wall_end') {
      var d = nd.legs[0][1];
      if (!slabAlong(slabAt, nd.pt, [-d[0], -d[1]], tmax * 0.0, dmAt)) nd.flags.push('wall end at slab edge');
    }
  });

  var posOn = [];
  for (var z2 = 0; z2 < n; z2++) posOn.push([]);
  nodes.forEach(function (nd) {
    nd.legs.forEach(function (l) {
      var j = l[0], s = W[j].sOf(nd.pt);
      if (!posOn[j].length || posOn[j].every(function (q) { return Math.abs(s - q) > 1.0; })) posOn[j].push(s);
    });
  });
  function legLen(j, s, d) {
    var w = W[j], fwd = dot(d, w.u) > 0, cand = [];
    posOn[j].forEach(function (q) { if (fwd ? q - s > 1.0 : s - q > 1.0) cand.push(fwd ? q - s : s - q); });
    return cand.length ? Math.min.apply(null, cand) : (fwd ? w.L - s : s);
  }

  var intervals = [];
  for (var z3 = 0; z3 < n; z3++) intervals.push([]);
  nodes.forEach(function (nd, ni) {
    if (KINDS_NODE.indexOf(nd.kind) < 0) return;
    var dm = dmAt(nd.pt[0], nd.pt[1]);
    nd.dm = dm;
    nd.legInfo = nd.legs.map(function (l) {
      var j = l[0], d = l[1], w = W[j];
      var others = nd.legs.filter(function (m) { return m[0] !== j; }).map(function (m) { return W[m[0]].t; });
      var zlen = p.k_zone * dm + (others.length ? Math.max.apply(null, others) / 2.0 : 0.0);
      var s = w.sOf(nd.pt), lo, hi;
      if (dot(d, w.u) > 0) { lo = s; hi = Math.min(s + zlen, w.L); } else { lo = Math.max(s - zlen, 0.0); hi = s; }
      if (hi - lo > 1.0) intervals[j].push([lo, hi, ni, s]);
      return {wall: w.id, t: w.t, len: legLen(j, s, d), ux: d[0], uy: d[1]};
    });
  });

  var others = [];
  W.forEach(function (w) {
    if (pylon[w.i]) return;
    var iv = intervals[w.i].slice().sort(function (r1, r2) { return r1[0] - r2[0] || r1[1] - r2[1]; });
    for (var a = 0; a < iv.length - 1; a++) {
      var p1 = iv[a], p2 = iv[a + 1];
      if (p1[2] !== p2[2] && p1[1] > p2[0] + 1.0) {
        var cut = (p1[3] + p2[3]) / 2.0;
        p1[1] = Math.min(p1[1], cut); p2[0] = Math.max(p2[0], cut);
        [p1, p2].forEach(function (q) { var fl = nodes[q[2]].flags; if (fl.indexOf('short leg') < 0) fl.push('short leg'); });
      }
    }
    var midSrc = [], cur = 0.0;
    iv.forEach(function (r) {
      var lo = r[0], hi = r[1], ni = r[2];
      if (hi - lo > 1.0) { var a1 = w.pt(lo); (nodes[ni].src = nodes[ni].src || []).push(['seg', a1[0], a1[1], w.u[0], w.u[1], hi - lo, w.t / 2.0]); }
      if (lo - cur > 1.0) { var a2 = w.pt(cur); midSrc.push(['seg', a2[0], a2[1], w.u[0], w.u[1], lo - cur, w.t / 2.0]); }
      cur = Math.max(cur, hi);
    });
    if (w.L - cur > 1.0) { var a3 = w.pt(cur); midSrc.push(['seg', a3[0], a3[1], w.u[0], w.u[1], w.L - cur, w.t / 2.0]); }
    if (midSrc.length) others.push({kind: 'wall_mid', ids: [w.id], links: [w.link], names: [w.name], src: midSrc, L: w.L, t: w.t});
  });

  nodes.forEach(function (nd) {
    if (KINDS_NODE.indexOf(nd.kind) < 0 || !nd.src) return;
    var ids = [], links = [], names = [];
    nd.legs.forEach(function (l) {
      var w = W[l[0]];
      if (ids.indexOf(w.id) < 0) { ids.push(w.id); links.push(w.link); names.push(w.name); }
    });
    var dims = {legs: nd.legInfo, dm: nd.dm};
    if (nd.angle != null) dims.angle = nd.angle;
    points.push({kind: nd.kind, x: nd.pt[0], y: nd.pt[1], ids: ids, links: links, names: names, dims: dims, flags: nd.flags, src: nd.src});
  });

  var used = [];
  supportedBeams(beams, W, cols, notes, beamForce).forEach(function (bm) {
    var g = bm.geo;
    used.push(bm.b.id);
    others.push({kind: 'beam', ids: [bm.b.id], links: [bm.b.link || ''], names: [bm.b.name || ''], L: g[2], t: g[3],
      src: [['seg', g[0][0], g[0][1], g[1][0], g[1][1], g[2], g[3] / 2.0]]});
  });

  var stats = {nodes: {}};
  nodes.forEach(function (nd) { stats.nodes[nd.kind] = (stats.nodes[nd.kind] || 0) + 1; });
  stats.pylons = pylon.filter(Boolean).length;
  return {points: points, others: others, notes: notes, stats: stats, beamsUsed: used};
}

// ------------------------------------------------------------------ classify
function march(g, c, d, face, across, perp, limit) {
  var step = g.s / 2.0, best = null, cause = null, offs = [0.0, 0.45 * across, -0.45 * across];
  for (var o = 0; o < 3; o++) {
    var t = 0.0;
    while (t <= limit) {
      var x = c[0] + d[0] * (face + t) + perp[0] * offs[o], y = c[1] + d[1] * (face + t) + perp[1] * offs[o];
      var k = g.kindAt(x, y);
      if (k !== SLAB) { if (best === null || t < best) { best = t; cause = k === HOLE ? 'hole' : 'edge'; } break; }
      t += step;
    }
  }
  return [best, cause];
}
function classifyColumn(g, pt, dm, p) {
  var src = pt.src[0], c = [src[1], src[2]], u = [src[3], src[4]], v = [-u[1], u[0]], hx = src[5], hy = src[6];
  var limEdge = p.edge_k * dm, limOpen = p.opening_k * dm, openFlag = 'opening ≤ ' + fmtG(p.opening_k) + 'd';
  var dirs = [[u, hx, 2 * hy, v, 'u'], [[-u[0], -u[1]], hx, 2 * hy, v, 'u'], [v, hy, 2 * hx, u, 'v'], [[-v[0], -v[1]], hy, 2 * hx, u, 'v']];
  var near = [], flags = [], dmin = null;
  dirs.forEach(function (dr) {
    var r = march(g, c, dr[0], dr[1], dr[2], dr[3], limOpen), t = r[0], cause = r[1];
    if (t === null) return;
    dmin = dmin === null ? t : Math.min(dmin, t);
    if (t <= limEdge) near.push([dr[4], cause]);
    else if (cause === 'hole' && flags.indexOf(openFlag) < 0) flags.push(openFlag);
  });
  var cls;
  if (!near.length) cls = 'int';
  else if (near.length === 1) cls = 'edge';
  else if (near.length === 2 && near[0][0] !== near[1][0]) cls = 'corner';
  else if (near.length === 2) { cls = 'edge'; flags.push('narrow strip'); }
  else { cls = 'corner'; flags.push('slab narrow on 3 sides'); }
  if (near.some(function (x) { return x[1] === 'hole'; })) flags.push('edge = opening');
  return [cls, flags, dmin, cls === 'edge' ? near[0][0] : null];
}
function nodeNearEdge(g, pt, dm, p, extra) {
  var lim = p.edge_k * dm + extra, step = g.s / 2.0, found = null;
  for (var a = 0; a < 16; a++) {
    var ang = a * Math.PI / 8.0, d = [Math.cos(ang), Math.sin(ang)], t = 0.0;
    while (t <= lim) {
      var k = g.kindAt(pt[0] + d[0] * t, pt[1] + d[1] * t);
      if (k !== SLAB) { var cause = k === HOLE ? 'hole' : 'edge'; if (found === null || cause === 'edge') found = cause; break; }
      t += step;
    }
  }
  return found === 'edge' ? ['near slab edge'] : found === 'hole' ? ['near opening'] : [];
}
function fmtG(v) { return String(+v); }

// ------------------------------------------------------------------ punching (поля строки)
var CALC = {'column:int': 'v6: col-int', 'column:edge': 'v6: col-edge', 'column:corner': 'v6: col-corner',
  'pylon:int': 'v6: wall-int', 'pylon:edge': 'v6: wall-edge', 'pylon:corner': 'v6: wall-corner', wall_L: 'wall-corner_v2'};
function rowFields(pt) {
  var kind = pt.kind, cls = pt.cls, r = {c1: null, c2: null, ta: null, tb: null, angle: null};
  var colLike = kind === 'column' || kind === 'pylon';
  r.calc = CALC[colLike ? kind + ':' + cls : kind] || '—';
  r.bkey = colLike ? kind + ':' + cls : kind;
  var dims = pt.dims;
  if (colLike) {
    if (dims.shape === 'round') { r.c1 = r.c2 = pyRound(dims.b); }
    else { r.c1 = pyRound(dims.b); r.c2 = pyRound(dims.h); }
  } else {
    var legs = (dims.legs || []).slice().sort(function (a, b) { return b.len - a.len; });
    if (kind === 'wall_L' && legs.length >= 2) {
      r.c1 = pyRound(legs[0].len); r.c2 = pyRound(legs[1].len); r.ta = pyRound(legs[0].t); r.tb = pyRound(legs[1].t);
      r.angle = dims.angle != null ? pyRound(dims.angle) : null;
    } else if (legs.length) {
      r.c1 = pyRound(legs[0].len); r.ta = pyRound(legs[0].t);
      if (legs.length > 1) { r.c2 = pyRound(legs[1].len); r.tb = pyRound(legs[1].t); }
    }
  }
  return r;
}

// ------------------------------------------------------------------ check (порт check.py: Excel «חישוב חדירה»)
var PUNCH_DEFAULTS = {fck: 30.0, top_d1: 0.0, top_s1: 200.0, top_d2: 0.0, top_s2: 200.0, sigma_cp: 0.0, sr: 0.0, alpha_w: 90.0, alpha_b: 45.0};
var RESULT_LABEL = {ok: 'OK — no punching reinforcement', reinf: 'Punching reinforcement required',
  thick_max: 'Increase slab thickness (β·V_d > V_Rd,max)', thick_c: 'Increase slab thickness (V_eq > 1.5·V_Rd,c)'};
function punchInputs(p, over) {
  var r = {}, k;
  for (k in PUNCH_DEFAULTS) r[k] = PUNCH_DEFAULTS[k];
  for (k in PUNCH_DEFAULTS) if (p && p[k] != null) r[k] = +p[k];
  if (over) for (k in over) if (k in PUNCH_DEFAULTS && over[k] != null && over[k] !== '') r[k] = +over[k];
  if (!(r.top_d1 > 0)) r.top_d1 = +((p || {}).bar_d || 12.0);
  return r;
}
function perim(kind, cls, c1, c2, shape, t, dm, eax) {
  var d = dm / 1000.0, flags = [], PI = Math.PI, u0;
  if (kind === 'column' || kind === 'pylon') {
    var a1 = (c1 || 0.0) / 1000.0, a2 = (c2 || 0.0) / 1000.0, rnd = shape === 'round';
    if ((cls === 'edge' || cls === 'corner') && rnd) { a1 = a2 = a1 * Math.sqrt(PI) / 2.0; rnd = false; flags.push('round column at edge: equivalent square'); }
    if (cls === 'edge') {
      var perp = eax !== 'v' ? a1 : a2, par = eax !== 'v' ? a2 : a1, cp = Math.min(par, 3.0 * d), cq = Math.min(perp, 1.5 * d);
      u0 = cp + 2.0 * cq;
      return {shape: 'col_edge', u0: u0, u1: u0 + 2.0 * PI * d, A: cp * cq + 2.0 * d * cp + 4.0 * d * cq + 2.0 * PI * d * d, sk: 1.0 / PI, flags: flags};
    }
    if (cls === 'corner') {
      var q1 = Math.min(a1, 1.5 * d), q2 = Math.min(a2, 1.5 * d);
      u0 = q1 + q2;
      return {shape: 'col_corner', u0: u0, u1: u0 + PI * d, A: q1 * q2 + 2.0 * d * (q1 + q2) + PI * d * d, sk: 2.0 / PI, flags: flags};
    }
    if (rnd) return {shape: 'round_int', u0: PI * a1, u1: PI * (a1 + 4.0 * d), A: PI * Math.pow(a1 + 4.0 * d, 2) / 4.0, sk: null, D: a1, flags: flags};
    var a = Math.max(a1, a2), b = Math.min(a1, a2), a_ = Math.min(a, 3.0 * d);
    u0 = 2.0 * a_ + 2.0 * b;
    return {shape: 'col_int', u0: u0, u1: u0 + 4.0 * PI * d, A: a_ * b + 4.0 * d * (a_ + b) + 4.0 * PI * d * d, sk: 1.0 / (2.0 * PI), flags: flags};
  }
  if (kind === 'wall_end') {
    var B = (t || 0.0) / 1000.0; u0 = B + 3.0 * d;
    return {shape: 'wall_end', u0: u0, u1: u0 + 2.0 * PI * d, A: 6.0 * d * d + 2.0 * B * d + 2.0 * PI * d * d, sk: 1.0 / PI, flags: flags};
  }
  if (kind === 'wall_L') { u0 = 3.0 * d; return {shape: 'wall_L', u0: u0, u1: u0 + PI * d, A: 6.0 * d * d + PI * d * d, sk: 2.0 / PI, flags: flags}; }
  return null;
}
function perimOf(pt) {
  var dims = pt.dims || {};
  if (pt.kind === 'column' || pt.kind === 'pylon') return perim(pt.kind, pt.cls, dims.b, dims.h, dims.shape, null, pt.dm, pt.eax);
  var legs = (dims.legs || []).slice().sort(function (a, b) { return b.len - a.len; });
  return perim(pt.kind, null, null, null, null, legs.length ? legs[0].t : null, pt.dm, null);
}
function rhoTop(dm, inp) {
  var As = 0.0;
  [['top_d1', 'top_s1'], ['top_d2', 'top_s2']].forEach(function (k) {
    if (inp[k[0]] > 0 && inp[k[1]] > 0) As += Math.PI / 4.0 * Math.pow(inp[k[0]], 2) * 1000.0 / inp[k[1]];
  });
  return dm > 0 ? As / (1000.0 * dm) : 0.0;
}
function punch(geo, dm, Vd, qd, beta, inp) {
  if (!geo || !dm || dm <= 0 || Vd == null || !beta) return null;
  var d = dm / 1000.0, fck = inp.fck, scp = inp.sigma_cp, fc = 0.7 * fck;
  var K = Math.min(2.0, 1.0 + Math.sqrt(200.0 / dm)), rho = rhoTop(dm, inp);
  var vMin = 0.035 * Math.pow(K, 1.5) * Math.sqrt(fc) + 0.1 * scp, vC = 0.12 * K * Math.pow(100.0 * rho * fc, 1.0 / 3.0) + 0.1 * scp, v = Math.max(vMin, vC);
  var u0 = geo.u0, u1 = geo.u1, Au1 = geo.A;
  var VRdc = v * u1 * d * 1000.0, VRdmax = 0.24 * (1.0 - 0.7 * fck / 250.0) * 0.93 * 0.7 / 1.5 * fck * u0 * d * 1000.0;
  var Veq = beta * Vd - beta * qd * Au1, bVd = beta * Vd, res;
  if (bVd > VRdmax) res = 'thick_max'; else if (Veq > 1.5 * VRdc) res = 'thick_c'; else if (VRdc > Veq) res = 'ok'; else res = 'reinf';
  var need = Veq > VRdc, rhoMin = need ? 0.005 : Math.max(0.0013, 0.28 * 0.3 * Math.pow(fc, 2.0 / 3.0) / 500.0), rhoMax = need ? 0.02 : 0.04;
  var out = {res: res, label: RESULT_LABEL[res], shape: geo.shape, u0: u0, u1: u1, Au1: Au1, K: K, rho: rho, rho_min: rhoMin, rho_max: rhoMax,
    v_min: vMin, v_c: vC, VRdc: VRdc, VRdmax: VRdmax, Veq: Veq, bVd: bVd, eta: VRdc > 0 ? Veq / VRdc : null, eta_max: VRdmax > 0 ? bVd / VRdmax : null,
    u_out: null, s_out: null, sr: null, Asw: null, Asa: null, Asb: null, m: null, warn: (geo.flags || []).slice()};
  if (res === 'reinf' && rho < rhoMin) out.warn.push('ρ < ρ_min: increase top reinforcement');
  if (rho > rhoMax) out.warn.push('ρ > ρ_max');
  if (need) {
    out.Asb = Veq * 1000.0 / 435.0 / 100.0;
    var uOut = Veq / (v * d * 1000.0);
    out.u_out = uOut;
    var sOut = geo.shape === 'round_int' ? 0.5 * (uOut / Math.PI - geo.D) : (uOut - u0) * geo.sk;
    out.s_out = sOut;
    if (Veq <= VRdmax) {
      var sr = inp.sr > 0 ? inp.sr / 1000.0 : Math.floor(0.75 * dm / 10.0) * 10.0 / 1000.0;
      var fy = Math.min(250.0 + 0.25 * dm, 435.0), dV = (Veq - 0.75 * VRdc) * 1000.0;
      out.sr = sr;
      out.Asw = dV / (1.5 * (d / sr) * fy * Math.sin(inp.alpha_w * (Math.PI / 180.0))) / 100.0;
      out.Asa = dV / (fy * Math.sin(inp.alpha_b * (Math.PI / 180.0))) / 100.0;
      var m = Math.ceil((sOut - 2.0 * d) / sr - 1e-9);
      out.m = Math.max(m, 2);
      if (m < 2) out.warn.push('perimeters: min 2 (EC2 9.4.3)');
    }
  }
  return out;
}

// ------------------------------------------------------------------ vector
function ownerGrid(g, label, ownerOfSrc, noneOwner, pad) {
  var nx = g.nx, ny = g.ny, kind = g.kind, N = nx * ny, O = new Int32Array(N).fill(-1);
  for (var idx = 0; idx < N; idx++) if (kind[idx] === SLAB) { var li = label[idx]; O[idx] = li >= 0 ? ownerOfSrc[li] : noneOwner; }
  var frontier = [];
  for (var i2 = 0; i2 < N; i2++) {
    if (O[i2] < 0) continue;
    var i = i2 % nx, j = (i2 - i) / nx;
    if ((i > 0 && O[i2 - 1] < 0) || (i < nx - 1 && O[i2 + 1] < 0) || (j > 0 && O[i2 - nx] < 0) || (j < ny - 1 && O[i2 + nx] < 0)) frontier.push(i2);
  }
  var D4 = [[-1, 0], [1, 0], [0, -1], [0, 1]];
  for (var step = 0; step < (pad == null ? 2 : pad); step++) {
    var nxt = [];
    frontier.forEach(function (id) {
      var ci = id % nx, cj = (id - ci) / nx;
      D4.forEach(function (d) {
        var ii = ci + d[0], jj = cj + d[1];
        if (ii >= 0 && ii < nx && jj >= 0 && jj < ny) { var k = jj * nx + ii; if (O[k] < 0) { O[k] = O[id]; nxt.push(k); } }
      });
    });
    frontier = nxt;
  }
  return O;
}
function dp(pts, tol) {
  var n = pts.length;
  if (n < 3) return pts.slice();
  var keep = new Uint8Array(n); keep[0] = keep[n - 1] = 1;
  var stack = [[0, n - 1]];
  while (stack.length) {
    var ab = stack.pop(), a = ab[0], b = ab[1];
    if (b - a < 2) continue;
    var ax = pts[a][0], ay = pts[a][1], dx = pts[b][0] - ax, dy = pts[b][1] - ay, L = Math.sqrt(dx * dx + dy * dy), best = -1.0, bi = -1;
    for (var k = a + 1; k < b; k++) {
      var px = pts[k][0], py = pts[k][1];
      var d = L < 1e-9 ? Math.sqrt((px - ax) * (px - ax) + (py - ay) * (py - ay)) : Math.abs(dx * (py - ay) - dy * (px - ax)) / L;
      if (d > best) { best = d; bi = k; }
    }
    if (best > tol) { keep[bi] = 1; stack.push([a, bi]); stack.push([bi, b]); }
  }
  var out = []; for (var q = 0; q < n; q++) if (keep[q]) out.push(pts[q]);
  return out;
}
function regions(g, O, tolCells) {
  var nx = g.nx, ny = g.ny, s = g.s, Wd = nx + 1, edges = [], adj = new Map();
  function own(i, j) { return i >= 0 && i < nx && j >= 0 && j < ny ? O[j * nx + i] : -1; }
  function add(va, vb, l, r) {
    var e = edges.length; edges.push([va, vb, l, r]);
    if (!adj.has(va)) adj.set(va, []); adj.get(va).push(e);
    if (!adj.has(vb)) adj.set(vb, []); adj.get(vb).push(e);
  }
  for (var j = 0; j <= ny; j++) for (var i = 0; i < nx; i++) {
    var below = own(i, j - 1), above = own(i, j);
    if (below !== above) add(j * Wd + i, j * Wd + i + 1, above, below);
  }
  for (var i2 = 0; i2 <= nx; i2++) for (var j2 = 0; j2 < ny; j2++) {
    var lc = own(i2 - 1, j2), rc = own(i2, j2);
    if (lc !== rc) add(j2 * Wd + i2, (j2 + 1) * Wd + i2, lc, rc);
  }
  var used = new Uint8Array(edges.length);
  function walk(v0, e0) {
    var verts = [v0], v = v0, e = e0, E0 = edges[e0];
    var left = E0[0] === v0 ? E0[2] : E0[3], right = E0[0] === v0 ? E0[3] : E0[2];
    for (;;) {
      used[e] = 1;
      var ed = edges[e], u = ed[0] === v ? ed[1] : ed[0];
      verts.push(u);
      var au = adj.get(u);
      if (au.length !== 2) break;
      var nxt = -1; for (var q = 0; q < au.length; q++) if (!used[au[q]]) { nxt = au[q]; break; }
      if (nxt < 0) break;
      v = u; e = nxt;
    }
    return [verts, left, right];
  }
  var chains = [];
  adj.forEach(function (es, v) {
    if (es.length === 2) return;
    es.forEach(function (e) { if (!used[e]) chains.push(walk(v, e)); });
  });
  for (var e = 0; e < edges.length; e++) if (!used[e]) chains.push(walk(edges[e][0], e));
  var tol = (tolCells == null ? 1.0 : tolCells) * s, x0 = g.x0, y0 = g.y0;
  function xy(v) { var ii = v % Wd; return [x0 + ii * s, y0 + ((v - ii) / Wd) * s]; }
  var pieces = new Map();
  chains.forEach(function (ch) {
    var verts = ch[0], left = ch[1], right = ch[2], pts = verts.map(xy), sp;
    if (verts[0] === verts[verts.length - 1] && pts.length > 3) {
      var far = 0, fd = -1;
      for (var k = 0; k < pts.length; k++) { var dd = (pts[k][0] - pts[0][0]) * (pts[k][0] - pts[0][0]) + (pts[k][1] - pts[0][1]) * (pts[k][1] - pts[0][1]); if (dd > fd) { fd = dd; far = k; } }
      sp = dp(pts.slice(0, far + 1), tol).slice(0, -1).concat(dp(pts.slice(far), tol));
    } else sp = dp(pts, tol);
    var vs = verts[0], ve = verts[verts.length - 1];
    if (left >= 0) { if (!pieces.has(left)) pieces.set(left, []); pieces.get(left).push([vs, ve, sp]); }
    if (right >= 0) { if (!pieces.has(right)) pieces.set(right, []); pieces.get(right).push([ve, vs, sp.slice().reverse()]); }
  });
  var out = new Map();
  pieces.forEach(function (ps, owner) {
    var byStart = new Map();
    ps.forEach(function (pc, k) { if (!byStart.has(pc[0])) byStart.set(pc[0], []); byStart.get(pc[0]).push(k); });
    var done = new Uint8Array(ps.length), rings = [];
    for (var k0 = 0; k0 < ps.length; k0++) {
      if (done[k0]) continue;
      done[k0] = 1;
      var vs = ps[k0][0], ve = ps[k0][1], ring = ps[k0][2].slice(), start = vs, guard = 0;
      while (ve !== start && guard < ps.length) {
        guard++;
        var cand = (byStart.get(ve) || []).filter(function (k) { return !done[k]; });
        if (!cand.length) break;
        var kk = cand[0]; done[kk] = 1; ve = ps[kk][1]; ring = ring.concat(ps[kk][2].slice(1));
      }
      if (ring.length > 1 && ring[0][0] === ring[ring.length - 1][0] && ring[0][1] === ring[ring.length - 1][1]) ring.pop();
      if (ring.length >= 3) rings.push(ring);
    }
    out.set(owner, rings);
  });
  return out;
}

// ------------------------------------------------------------------ pipeline
function objKey(kind, link, id) { return kind + ':' + (link || '') + ':' + id; }
/* data  — как из collect.py (slabs, walls, columns, beams)
 * p     — params.merged(...) из Python (+ правки из схемы)
 * opts  — {off: Set ключей 'w:link:id' / 'c:link:id' / 'b:link:id', beamOn: {id: true}, regions: true}
 */
function run(data, p, opts) {
  opts = opts || {};
  var t0 = Date.now(), off = opts.off || new Set();
  var slabs = data.slabs, g = new Grid(slabs, p.grid_mm);
  function dmAt(x, y) { return dM(g.hNear(x, y), p); }
  function slabAt(x, y) { return g.kindAt(x, y) === SLAB; }
  var walls = (data.walls || []).filter(function (w) { return !off.has(objKey('w', w.link, w.id)); });
  var columns = (data.columns || []).filter(function (c) { return !off.has(objKey('c', c.link, c.id)); });
  var beams = (+p.use_beams ? (data.beams || []) : []).filter(function (b) { return !off.has(objKey('b', b.link, b.id)); });
  var topo = build(walls, columns, beams, p, dmAt, slabAt, opts.beamOn || {});
  var points = topo.points, others = topo.others, sources = [], owner = [];
  points.forEach(function (pt, i) { pt.src.forEach(function (s) { sources.push(s); owner.push(i); }); });
  others.forEach(function (ot, i) { ot.src.forEach(function (s) { sources.push(s); owner.push(points.length + i); }); });
  var asg = assign(g, sources), ar = areasBySlab(g, asg.label, sources.length);
  function floorOf(k) { return slabs[k].id != null ? slabs[k].id : k; }
  var all = points.concat(others);
  all.forEach(function (o) { o.area = 0.0; o.afMap = new Map(); });
  ar.bySrc.forEach(function (d, si) {
    var o = all[owner[si]];
    d.forEach(function (a, k) { o.area += a; var f = floorOf(k); o.afMap.set(f, (o.afMap.get(f) || 0.0) + a); });
  });
  var noneArea = 0.0, noneBy = new Map();
  ar.none.forEach(function (a, k) { noneArea += a; var f = floorOf(k); noneBy.set(f, (noneBy.get(f) || 0.0) + a); });

  var notes = topo.notes.slice(), kept = [], dropped = [];
  points.forEach(function (pt) {
    if (pt.area <= 0.0) { dropped.push(pt); return; }
    pt.h = g.hNear(pt.x, pt.y); pt.dm = dM(pt.h, p);
    if (pt.kind === 'column' || pt.kind === 'pylon') {
      var r = classifyColumn(g, pt, pt.dm, p);
      pt.cls = r[0]; pt.edge = r[2]; pt.eax = r[3]; pt.flags = pt.flags.concat(r[1]);
    } else {
      pt.cls = null;
      var extra = pt.dims.legs && pt.dims.legs.length ? Math.max.apply(null, pt.dims.legs.map(function (l) { return l.t; })) / 2.0 : 0.0;
      pt.flags = pt.flags.concat(nodeNearEdge(g, [pt.x, pt.y], pt.dm, p, extra));
    }
    kept.push(pt);
  });
  kept.sort(function (a, b) { var ka = -pyRound(a.y / 500.0), kb = -pyRound(b.y / 500.0); return ka - kb || a.x - b.x; });
  kept.forEach(function (pt, i) { pt.n = i + 1; });

  function af(m) { var o = {}; m.forEach(function (a, f) { if (a > 0) o[String(f)] = pyRound(a / 1e6, 3); }); return o; }
  var outPts = kept.map(function (pt) {
    var rf = rowFields(pt), o = {n: pt.n, kind: pt.kind, cls: pt.cls, x: pyRound(pt.x), y: pyRound(pt.y),
      key: pt.kind + ':' + pt.ids.join(','), bkey: rf.bkey, ids: pt.ids.map(String),
      links: Array.from(new Set(pt.links.filter(Boolean))).sort(), flags: pt.flags,
      h: pyRound(pt.h), dm: pyRound(pt.dm), calc: rf.calc, c1: rf.c1, c2: rf.c2, ta: rf.ta, tb: rf.tb, angle: rf.angle,
      edge: pt.edge != null ? pyRound(pt.edge) : null, eax: pt.eax || null, dmExact: pt.dm,
      af: af(pt.afMap), A: pyRound(pt.area / 1e6, 2), areaMm2: pt.area, geo: perimOf(pt)};
    if (pt.kind === 'column' || pt.kind === 'pylon') { var s = pt.src[0]; o.geom = [s[0], s[1], s[2], s[3], s[4], s[5], s[6]]; }
    return o;
  });
  // ключ точки должен быть уникален: у свободной стены два торца с одним kind+ids — иначе схема
  // путала их (клик по одному показывал другой, k и ΔV общие). Дубликатам — положение, шаг 0.1 м
  var nKey = {};
  outPts.forEach(function (o) { nKey[o.key] = (nKey[o.key] || 0) + 1; });
  outPts.forEach(function (o) { if (nKey[o.key] > 1) o.key += '@' + Math.round(o.x / 100) + ',' + Math.round(o.y / 100); });
  var outOthers = others.map(function (ot, i) {
    return {i: i, kind: ot.kind, ids: ot.ids.map(String), links: Array.from(new Set(ot.links.filter(Boolean))).sort(),
      L: pyRound(ot.L || 0), t: pyRound(ot.t || 0), af: af(ot.afMap), A: pyRound(ot.area / 1e6, 2)};
  });

  var regs = [];
  if (opts.regions !== false) {
    var noneOwner = points.length + others.length;
    var O = ownerGrid(g, asg.label, owner, noneOwner, 2), rg = regions(g, O, 1.0);
    rg.forEach(function (rings, o) {
      var r;
      if (o < points.length) { if (!points[o].n) return; r = {t: 'point', n: points[o].n}; }
      else if (o < noneOwner) r = {t: others[o - points.length].kind, i: o - points.length};
      else r = {t: 'none'};
      r.rings = rings.map(function (ring) { return ring.map(function (q) { return [Math.round(q[0]), Math.round(q[1])]; }); });
      regs.push(r);
    });
  }

  var areaRaster = g.slabArea(), areaClosed = g.closed_cells * g.s * g.s;
  var areaPts = kept.reduce(function (t, q) { return t + q.area; }, 0), areaOth = others.reduce(function (t, q) { return t + q.area; }, 0);
  var check = {area_poly_m2: pyRound(g.area_poly / 1e6, 2), area_raster_m2: pyRound(areaRaster / 1e6, 2),
    area_joints_m2: pyRound(areaClosed / 1e6, 2), area_points_m2: pyRound(areaPts / 1e6, 2),
    area_walls_beams_m2: pyRound(areaOth / 1e6, 2), area_none_m2: pyRound(noneArea / 1e6, 2)};
  if (g.area_poly > 0 && Math.abs(areaRaster - areaClosed - g.area_poly) > 0.01 * g.area_poly)
    notes.push('raster area differs from the slab area by more than 1 % — check for overlapping slabs or reduce the grid step');
  if (g.overlaps.length) notes.push('slabs overlap in plan (no area correction): ' + Array.from(new Set(g.overlaps)).join(', '));
  if (noneArea > 0) notes.push((noneArea / 1e6).toFixed(2) + ' m² of slab without support (cantilever, or no supports under part of the slab)');
  if (dropped.length) notes.push(dropped.length + ' supports outside the slab — skipped');
  var nd = topo.stats.nodes, skipped = (nd.wall_L_in || 0) + (nd.wall_T || 0) + (nd.wall_X || 0);
  if (skipped) notes.push('concave corners are not checked: inner L — ' + (nd.wall_L_in || 0) + ', T — ' + (nd.wall_T || 0) +
    ', X — ' + (nd.wall_X || 0) + ' (their area goes to the walls)');
  var counts = {};
  outPts.forEach(function (q) { counts[q.kind] = (counts[q.kind] || 0) + 1; });
  return {points: outPts, others: outOthers, none: {af: af(noneBy), A: check.area_none_m2}, regions: regs,
    check: check, notes: notes, stats: topo.stats, counts: counts, beamsUsed: topo.beamsUsed, ms: Date.now() - t0};
}

return {run: run, objKey: objKey, pyRound: pyRound, perim: perim, punch: punch, punchInputs: punchInputs,
  RESULT_LABEL: RESULT_LABEL, version: '1.1'};
}));
