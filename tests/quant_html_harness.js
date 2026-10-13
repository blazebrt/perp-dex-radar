// Runs quant.html's page script against a minimal DOM and prints what the page shows (v8 Phase 9 tests).
//   node tests/quant_html_harness.js quant.html quant.json quant_research.json
// Prints {lede, stratTitle, stratNote, strats, kpis, all, method, errors} as JSON.
"use strict";
const fs = require("fs");
const vm = require("vm");

const [html, qPath, rPath] = process.argv.slice(2);
const src = fs.readFileSync(html, "utf8");
const scripts = [...src.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const page = scripts.reduce((a, b) => (b.length > a.length ? b : a));
const readJson = (p) => (p && p !== "-" ? JSON.parse(fs.readFileSync(p, "utf8")) : null);
const data = { "data/quant.json": readJson(qPath), "data/quant_research.json": readJson(rPath) };

class Node {
  constructor(tag) {
    this.tagName = tag; this.children = []; this.attrs = {}; this.style = {}; this.nodeType = 1; this._text = "";
    this.value = ""; this.checked = false; this.clientWidth = 640; this.clientHeight = 300; this.offsetWidth = 640;
    this.scrollWidth = 640; this.scrollLeft = 0;
    this.classList = { add() {}, remove() {}, toggle() {}, contains() { return false; } };
    this.dataset = {};
  }
  append(...kids) { for (const k of kids) this.children.push(typeof k === "string" ? new Text(k) : k); }
  appendChild(k) { this.append(k); return k; }
  prepend(...kids) { this.children.unshift(...kids.map((k) => (typeof k === "string" ? new Text(k) : k))); }
  setAttribute(k, v) { this.attrs[k] = String(v); }
  getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; }
  removeAttribute(k) { delete this.attrs[k]; }
  addEventListener() {}
  querySelector() { return null; }
  querySelectorAll() { return []; }
  getBoundingClientRect() { return { left: 0, top: 0, width: 640, height: 300, right: 640, bottom: 300 }; }
  getTotalLength() { return 100; }
  get textContent() { return this._text + this.children.map((c) => c.textContent).join(""); }
  set textContent(v) { this.children = []; this._text = String(v); }
  set innerHTML(v) { this.children = []; this._text = String(v); }
  get firstChild() { return this.children[0] || null; }
}
class Text { constructor(t) { this.nodeType = 3; this.textContent = String(t); } }

const byId = {};
const document = {
  documentElement: new Node("html"),
  getElementById(id) { return byId[id] || (byId[id] = new Node("div")); },
  createElement(tag) { return new Node(tag); },
  createElementNS(ns, tag) { return new Node(tag); },
  createTextNode(t) { return new Text(t); },
  querySelector() { return null; },
};
const errors = [];
const storage = {};
const ctx = {
  document, console, Math, JSON, Date, Object, Array, Number, String, Set, Map, Promise, isFinite, parseFloat, parseInt,
  Intl, setTimeout: () => 0, clearTimeout() {}, setInterval: () => 0,
  addEventListener() {}, getComputedStyle: () => ({ getPropertyValue: () => "" }),
  localStorage: { getItem: (k) => (k in storage ? storage[k] : null), setItem: (k, v) => { storage[k] = String(v); } },
  matchMedia: () => ({ matches: false, addEventListener() {} }),
  fetch: async (url) => {
    const key = String(url).split("?")[0];
    const body = data[key];
    return { ok: body !== null && body !== undefined, json: async () => body };
  },
};
ctx.window = ctx;
ctx.globalThis = ctx;
vm.createContext(ctx);
process.on("unhandledRejection", (e) => { errors.push(String(e && e.stack || e)); finish(); });
let done = false;
function finish() {
  if (done) return;
  done = true;
  const t = (id) => (byId[id] ? byId[id].textContent : null);
  process.stdout.write(JSON.stringify({ lede: t("lede"), stratTitle: t("stratTitle"), stratNote: t("stratNote"),
    strats: t("strats"), kpis: t("kpis"), all: t("allTable"), method: t("method"), errors }));
}
try {
  vm.runInContext(page, ctx, { filename: "quant.html" });
} catch (e) {
  errors.push(String(e && e.stack || e));
}
setImmediate(() => setImmediate(finish));
