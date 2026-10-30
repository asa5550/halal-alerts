// Halal Portfolio — iPhone home-screen widget for the Scriptable app.
// Reads widget.json from your PRIVATE GitHub repo (asa5550/halal-portfolio), written by the
// halal-alerts daily job. Works in small, medium and large sizes.
//
// Setup: paste this into a new Scriptable script, run it once in the app and paste your
// GitHub token when asked (stored in the iPhone Keychain, never in this file).

const OWNER = "asa5550";
const REPO = "halal-portfolio";
const FILE = "widget.json";
const KEY = "halal_widget_token";

const C = {
  bg: "#0f1724", card: "#182233", text: "#f1f4f9", dim: "#8b97ab", faint: "#2a364a",
  up: "#34c77b", down: "#ff6b5f", line: "#5aa9ff", cost: "#8b97ab",
  dom: { us_halal: "#5aa9ff", commodities: "#e3c35a", msx: "#b48cff" },
};

// ---------- data ----------
async function askToken() {
  const a = new Alert();
  a.title = "GitHub token";
  a.message = "Paste a fine-grained token with read-only Contents access to " + REPO + ".";
  a.addSecureTextField("github_pat_…", "");
  a.addAction("Save");
  a.addCancelAction("Cancel");
  if ((await a.present()) === -1) return null;
  const t = a.textFieldValue(0).trim();
  if (t) Keychain.set(KEY, t);
  return t || null;
}

async function loadData() {
  const fm = FileManager.local();
  const cache = fm.joinPath(fm.documentsDirectory(), "halal-widget-cache.json");
  let token = Keychain.contains(KEY) ? Keychain.get(KEY) : null;
  if (!token && !config.runsInWidget) token = await askToken();
  if (!token) return { error: "Run the script in Scriptable to add your GitHub token." };
  try {
    const r = new Request(`https://api.github.com/repos/${OWNER}/${REPO}/contents/${FILE}`);
    r.headers = { Authorization: "Bearer " + token, Accept: "application/vnd.github.raw+json",
                  "X-GitHub-Api-Version": "2022-11-28" };
    const txt = await r.loadString();
    const code = r.response && r.response.statusCode;
    if (code === 401 || code === 403) {
      if (!config.runsInWidget) Keychain.remove(KEY);
      return { error: "GitHub token rejected. Run the script to enter a new one." };
    }
    if (code === 404) return { error: "No widget data yet. It appears after the next daily run (09:17)." };
    const d = JSON.parse(txt);
    fm.writeString(cache, txt);
    return d;
  } catch (e) {
    if (fm.fileExists(cache)) { const d = JSON.parse(fm.readString(cache)); d.offline = true; return d; }
    return { error: "Couldn't reach GitHub: " + e };
  }
}

// ---------- formatting ----------
const omr = (v, big) => {
  if (v == null) return "—";
  const a = Math.abs(v), dp = big ? (a >= 1000 ? 0 : 2) : (a >= 100 ? 0 : a >= 10 ? 1 : 2);
  return v.toLocaleString("en-US", { minimumFractionDigits: dp, maximumFractionDigits: dp });
};
const pct = (p, dp = 1) => {
  if (p == null) return "—";
  const s = (p * 100).toFixed(dp);
  return Number(s) === 0 ? (0).toFixed(dp) + "%" : (p > 0 ? "+" : "") + s + "%";
};
const col = (h, a = 1) => new Color(h, a);
const ago = iso => {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 60 ? m + "m ago" : m < 1440 ? Math.round(m / 60) + "h ago" : Math.round(m / 1440) + "d ago";
};

// ---------- drawing ----------
function text(ctx, s, x, y, w, h, size, color, opts = {}) {
  ctx.setFont(opts.bold ? Font.boldSystemFont(size) : opts.medium ? Font.mediumSystemFont(size) : Font.systemFont(size));
  ctx.setTextColor(col(color));
  if (opts.align === "right") ctx.setTextAlignedRight();
  else if (opts.align === "center") ctx.setTextAlignedCenter();
  else ctx.setTextAlignedLeft();
  ctx.drawTextInRect(String(s), new Rect(x, y, w, h));
}

function roundRect(ctx, x, y, w, h, r, color) {
  const p = new Path();
  p.addRoundedRect(new Rect(x, y, w, h), r, r);
  ctx.addPath(p);
  ctx.setFillColor(col(color));
  ctx.fillPath();
}

function line(ctx, vals, x, y, w, h, color, opts = {}) {
  const v = vals.filter(n => n != null && isFinite(n));
  if (v.length < 2) return;
  const lo = opts.lo ?? Math.min(...v), hi = opts.hi ?? Math.max(...v), span = hi - lo || Math.abs(hi) || 1;
  const pts = v.map((n, i) => new Point(x + (i / (v.length - 1)) * w, y + h - ((n - lo) / span) * h));
  if (opts.fill) {
    const f = new Path();
    f.move(new Point(pts[0].x, y + h));
    pts.forEach(p => f.addLine(p));
    f.addLine(new Point(pts[pts.length - 1].x, y + h));
    f.closeSubpath();
    ctx.addPath(f);
    ctx.setFillColor(col(color, 0.18));
    ctx.fillPath();
  }
  const p = new Path();
  p.move(pts[0]);
  pts.slice(1).forEach(q => p.addLine(q));
  ctx.addPath(p);
  ctx.setStrokeColor(col(color, opts.alpha ?? 1));
  ctx.setLineWidth(opts.width ?? 2);
  ctx.strokePath();
  if (opts.dot) {
    const e = pts[pts.length - 1];
    ctx.setFillColor(col(color));
    ctx.fillEllipse(new Rect(e.x - 3, e.y - 3, 6, 6));
  }
}

function valueChart(ctx, d, x, y, w, h) {
  const hist = d.history || [];
  if (hist.length < 2) {
    const msg = (d.holdings || []).length ? "Chart builds as days pass" : "Log a trade in Telegram to start";
    text(ctx, msg, x, y + h / 2 - 8, w, 16, 11, C.dim, { align: "center" });
    return;
  }
  const vals = hist.map(p => p.v), cost = hist.map(p => p.c);
  const all = vals.concat(cost), lo = Math.min(...all), hi = Math.max(...all), pad = (hi - lo) * 0.08 || 1;
  line(ctx, cost, x, y, w, h, C.cost, { lo: lo - pad, hi: hi + pad, width: 1, alpha: 0.6 });
  const up = vals[vals.length - 1] >= cost[cost.length - 1];
  line(ctx, vals, x, y, w, h, up ? C.up : C.down, { lo: lo - pad, hi: hi + pad, fill: true, dot: true });
}

function header(ctx, d, x, y, w, big) {
  text(ctx, "Halal portfolio", x, y, w, 16, 12, C.dim, { medium: true });
  text(ctx, omr(d.total, true) + " OMR", x, y + 16, w, big ? 34 : 28, big ? 28 : 22, C.text, { bold: true });
  const up = (d.pnl ?? 0) >= 0, h = d.history || [];
  const day = h.length > 1 ? h[h.length - 1].v - h[h.length - 2].v : null;
  let s = `${up ? "▲" : "▼"} ${omr(Math.abs(d.pnl))} (${pct(d.pnl_pct)})`;
  text(ctx, s, x, y + (big ? 50 : 44), w, 16, 12, up ? C.up : C.down, { medium: true });
  if (day != null && big) text(ctx, `Today ${day >= 0 ? "+" : "−"}${omr(Math.abs(day))}`, x, y + 66, w, 16, 11, C.dim);
}

function allocation(ctx, d, x, y, w, rowH) {
  (d.domains || []).forEach((m, i) => {
    const yy = y + i * rowH, c = C.dom[m.key] || C.line;
    text(ctx, m.label.replace(" (spot)", ""), x, yy, w * 0.6, 14, 10, C.dim);
    text(ctx, `${Math.round(m.pct)}% / ${m.target}%`, x, yy, w, 14, 10, C.text, { align: "right", medium: true });
    const by = yy + 15;
    roundRect(ctx, x, by, w, 5, 2.5, C.faint);
    if (m.pct > 0) roundRect(ctx, x, by, Math.max(5, (w * Math.min(m.pct, 100)) / 100), 5, 2.5, c);
    const tx = x + (w * m.target) / 100;
    ctx.setFillColor(col(C.text, 0.85));
    ctx.fillRect(new Rect(tx - 1, by - 2, 2, 9));
  });
}

function rows(ctx, d, x, y, w, n) {
  const hold = d.holdings || [];
  const list = hold.length ? hold : (d.watch || []);
  text(ctx, hold.length ? "Holdings" : "Watching (no holdings yet)", x, y, w, 14, 11, C.dim, { medium: true });
  list.slice(0, n).forEach((r, i) => {
    const yy = y + 20 + i * 26;
    text(ctx, r.symbol, x, yy + 2, 60, 16, 13, C.text, { bold: true });
    text(ctx, r.signal || "", x + 58, yy + 4, 80, 14, 9, C.dim);
    const ch = hold.length ? r.pnl_pct : r.chg, up = (ch ?? 0) >= -0.0005;
    line(ctx, r.spark || [], x + w * 0.42, yy + 2, w * 0.22, 16, up ? C.up : C.down, { width: 1.5 });
    text(ctx, hold.length ? omr(r.value) : (r.last != null ? omr(r.last) : "—"), x + w * 0.66, yy + 2, w * 0.18, 16, 12, C.text,
         { align: "right" });
    text(ctx, pct(ch), x + w * 0.84, yy + 2, w * 0.16, 16, 12, up ? C.up : C.down, { align: "right", medium: true });
  });
}

function draw(d, family) {
  const S = { small: [170, 170], medium: [364, 170], large: [364, 382] }[family] || [364, 382];
  const [W, H] = S, P = 14;
  const ctx = new DrawContext();
  ctx.size = new Size(W, H);
  ctx.opaque = true;
  ctx.respectScreenScale = true;
  ctx.setFillColor(col(C.bg));
  ctx.fillRect(new Rect(0, 0, W, H));

  if (d.error) {
    text(ctx, "Halal portfolio", P, P, W - 2 * P, 16, 12, C.dim, { medium: true });
    text(ctx, d.error, P, P + 24, W - 2 * P, H - 40, 12, C.text);
    return ctx.getImage();
  }
  const stamp = (d.offline ? "offline · " : "") + ago(d.updated);

  if (family === "small") {
    header(ctx, d, P, P, W - 2 * P, false);
    valueChart(ctx, d, P, 76, W - 2 * P, H - 76 - 24);
    text(ctx, stamp, P, H - 20, W - 2 * P, 14, 9, C.dim);
  } else if (family === "medium") {
    const lw = W * 0.55;
    header(ctx, d, P, P, lw - P, false);
    valueChart(ctx, d, P, 78, lw - P - 6, H - 78 - 24);
    text(ctx, stamp, P, H - 20, lw, 14, 9, C.dim);
    allocation(ctx, d, lw + 6, P + 2, W - lw - 6 - P, 35);
  } else {
    header(ctx, d, P, P, W - 2 * P, true);
    text(ctx, stamp, P, P, W - 2 * P, 14, 9, C.dim, { align: "right" });
    valueChart(ctx, d, P, 92, W - 2 * P, 90);
    const half = (W - 3 * P) / 2;
    allocation(ctx, { domains: (d.domains || []).slice(0, 2) }, P, 194, half, 30);
    allocation(ctx, { domains: (d.domains || []).slice(2) }, P * 2 + half, 194, half, 30);
    ctx.setFillColor(col(C.faint));
    ctx.fillRect(new Rect(P, 252, W - 2 * P, 1));
    rows(ctx, d, P, 260, W - 2 * P, 4);
  }
  return ctx.getImage();
}

// ---------- run ----------
const data = await loadData();
const family = config.widgetFamily || "large";
const w = new ListWidget();
w.backgroundColor = col(C.bg);
w.setPadding(0, 0, 0, 0);
w.backgroundImage = draw(data, family);
w.refreshAfterDate = new Date(Date.now() + 15 * 60 * 1000);
if (config.runsInWidget) {
  Script.setWidget(w);
} else {
  const pick = new Alert();
  pick.title = "Preview";
  ["Small", "Medium", "Large", "Change GitHub token"].forEach(s => pick.addAction(s));
  pick.addCancelAction("Done");
  const i = await pick.present();
  if (i === 3) { Keychain.contains(KEY) && Keychain.remove(KEY); await askToken(); }
  else if (i >= 0) {
    const f = ["small", "medium", "large"][i];
    const pw = new ListWidget();
    pw.backgroundColor = col(C.bg);
    pw.setPadding(0, 0, 0, 0);
    pw.backgroundImage = draw(data, f);
    await ({ small: () => pw.presentSmall(), medium: () => pw.presentMedium(), large: () => pw.presentLarge() })[f]();
  }
}
Script.complete();
