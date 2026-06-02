#!/usr/bin/env node
/**
 * kb-9f1h.5 — composed-state browser read-back of the studio sequence.
 *
 * Re-runnable integration gate. Drives the LIVE app via the browser-automation
 * CLI scripts (Chrome on :9222, dev server on :8009) and asserts the 6-step
 * sequence against rendered DOM + post-click window.location (NOT response.context).
 *
 * Prereqs (see kb-9f1h.5 contract):
 *   - Chrome up on localhost:9222  (node ~/.claude/skills/browser-automation/start.js)
 *   - Dev server:  uv run python manage.py runserver 8009
 *   - Seed users (password "switch-smoke-2026", all email-verified):
 *       studio-demo@switch.test   claimant, >=1 Event + >=1 Post
 *       studio-empty@switch.test  claimant, zero publishables
 *       studio-noclaim@switch.test  authenticated, NO ProfileClaim
 *
 * Run:  node scripts/studio_readback.mjs
 * Exit: 0 = all 6 PASS, 1 = any FAIL.
 *
 * NOTE: pk values (events 46/47, post 4) are seed-specific — adjust EVENT_PK / POST_PK
 * if the seed changes, or generalize by reading the first event/post hx-push-url off the rail.
 */
import { execFileSync } from "node:child_process";

const BA = process.env.HOME + "/.claude/skills/browser-automation";
const BASE = "http://127.0.0.1:8009";
const LABEL = "studio";
const PW = "switch-smoke-2026";
const EVENT_PK = 47;
const POST_PK = 4;

let failures = 0;
const report = (step, pass, evidence) => {
  console.log(`${pass ? "PASS" : "FAIL"}  step ${step}: ${evidence}`);
  if (!pass) failures++;
};

const ba = (script, ...args) =>
  execFileSync("node", [`${BA}/${script}`, ...args], { encoding: "utf8" });
const evalJs = (expr) => ba("eval.js", `--label=${LABEL}`, expr).trim();
const nav = (url) => ba("nav.js", url, `--label=${LABEL}`);
const navNew = (url) => ba("nav.js", url, "--new", `--label=${LABEL}`);
const waitFn = (fn, t = 10000) => {
  try { ba("wait.js", `--label=${LABEL}`, `--fn=${fn}`, `--timeout=${t}`); return true; }
  catch { return false; }
};
const waitUrl = (sub, t = 10000) => {
  try { ba("wait.js", `--label=${LABEL}`, `--url=${sub}`, `--timeout=${t}`); return true; }
  catch { return false; }
};

const logout = () => {
  nav(`${BASE}/accounts/logout/`);
  evalJs(`(() => { const f = Array.from(document.querySelectorAll("form")).find(f => f.querySelector("button,input[type=submit]")); if(f) f.submit(); return "ok"; })()`);
};
const login = (email) => {
  nav(`${BASE}/accounts/login/`);
  evalJs(`(() => { const f=Array.from(document.querySelectorAll("form")).find(x=>x.querySelector("input[name=login]")); document.querySelector("input[name=login]").value=${JSON.stringify(email)}; document.querySelector("input[name=password]").value=${JSON.stringify(PW)}; f.submit(); return "ok"; })()`);
  waitFn(`document.readyState === "complete" && !location.pathname.includes("login")`);
};

// bootstrap a tab
navNew(`${BASE}/accounts/login/`);

// ---- as claimant ----
logout();
login("studio-demo@switch.test");

// Step 1A: navbar Studio link present
let r = JSON.parse(evalJs(`JSON.stringify({present: document.querySelector('nav a[href="/studio/"]') !== null})`));
const step1aPass = r.present === true;

nav(`${BASE}/studio/`);

// Step 2: rail lists >=1 Event + >=1 Post as peers, post shows parent subtitle
r = JSON.parse(evalJs(`(() => {
  const rows = Array.from(document.querySelectorAll("[hx-push-url]"));
  const ev = rows.filter(x=>/\\/events\\//.test(x.getAttribute("hx-push-url")));
  const po = rows.filter(x=>/\\/posts\\//.test(x.getAttribute("hx-push-url")));
  return JSON.stringify({hasMain: !!document.querySelector("#studio-main"), events: ev.length, posts: po.length, postArrow: po[0] ? /↳/.test(po[0].textContent) : false});
})()`));
report(2, r.hasMain && r.events >= 1 && r.posts >= 1 && r.postArrow,
  `#studio-main present, ${r.events} event row(s) + ${r.posts} post row(s) as peers, post parent-subtitle ↳=${r.postArrow}`);

// Step 3: Event row click -> composer in #studio-main AND window.location pushed
evalJs(`(() => { Array.from(document.querySelectorAll("[hx-push-url]")).find(x=>x.getAttribute("hx-push-url")==="/syndication/events/${EVENT_PK}/").click(); return "ok"; })()`);
waitUrl(`/syndication/events/${EVENT_PK}/`);
r = JSON.parse(evalJs(`(() => { const m=document.querySelector("#studio-main"); const t=m?m.textContent:""; return JSON.stringify({path: location.pathname, rendered: !!m && !/Select a publishable from the rail/.test(t) && t.trim().length>0, nested: m ? (!!m.querySelector("html")||!!m.querySelector("body")) : true}); })()`));
report(3, r.path === `/syndication/events/${EVENT_PK}/` && r.rendered && !r.nested,
  `window.location.pathname="${r.path}", composer rendered in #studio-main=${r.rendered}, no nested html/body=${!r.nested}`);

// Step 4: Post row click -> composer in #studio-main AND window.location pushed
evalJs(`(() => { Array.from(document.querySelectorAll("[hx-push-url]")).find(x=>x.getAttribute("hx-push-url")==="/syndication/posts/${POST_PK}/").click(); return "ok"; })()`);
waitUrl(`/syndication/posts/${POST_PK}/`);
r = JSON.parse(evalJs(`(() => { const m=document.querySelector("#studio-main"); const t=m?m.textContent:""; return JSON.stringify({path: location.pathname, rendered: !!m && !/Select a publishable from the rail/.test(t) && t.trim().length>0, nested: m ? (!!m.querySelector("html")||!!m.querySelector("body")) : true}); })()`));
report(4, r.path === `/syndication/posts/${POST_PK}/` && r.rendered && !r.nested,
  `window.location.pathname="${r.path}", composer rendered in #studio-main=${r.rendered}, no nested html/body=${!r.nested}`);

// ---- as zero-publishables claimant ----
logout();
login("studio-empty@switch.test");
nav(`${BASE}/studio/`);

// Step 5: empty-state CTA, not blank list
r = JSON.parse(evalJs(`(() => {
  const rows = document.querySelectorAll("[hx-push-url]").length;
  const cta = Array.from(document.querySelectorAll("a")).find(a => /create/i.test(a.textContent) && /event/i.test(a.textContent + " " + (a.getAttribute("href")||"")));
  return JSON.stringify({rows, ctaText: cta ? cta.textContent.replace(/\\s+/g," ").trim() : null, ctaHref: cta ? cta.getAttribute("href") : null});
})()`));
report(5, r.rows === 0 && !!r.ctaText,
  `${r.rows} rows, empty-state CTA "${r.ctaText}" -> ${r.ctaHref} (not a blank list)`);

// ---- as zero-claims user ----
logout();
login("studio-noclaim@switch.test");

// Step 1B: navbar Studio link absent
r = JSON.parse(evalJs(`JSON.stringify({present: document.querySelector('nav a[href="/studio/"]') !== null})`));
const step1bPass = r.present === false;
report(1, step1aPass && step1bPass, `Studio link present for claimant=${step1aPass}, absent for non-claimant=${step1bPass}`);

// Step 6: /studio/ refuses (403 or redirect), no workspace
const fetchRes = JSON.parse(evalJs(`(async () => { const r = await fetch("/studio/", {redirect:"manual"}); return JSON.stringify({status: r.status, type: r.type}); })()`));
nav(`${BASE}/studio/`);
const dom = JSON.parse(evalJs(`(() => JSON.stringify({rail: !!document.querySelector("[hx-push-url]"), main: !!document.querySelector("#studio-main")}))()`));
const refused = fetchRes.status === 403 || fetchRes.type === "opaqueredirect" || (fetchRes.status >= 300 && fetchRes.status < 400);
report(6, refused && !dom.rail && !dom.main,
  `fetch /studio/ status=${fetchRes.status} type=${fetchRes.type}; rendered rail=${dom.rail}, #studio-main=${dom.main} (no synthesized workspace)`);

console.log(failures === 0 ? "\nALL 6 STEPS PASS" : `\n${failures} STEP(S) FAILED`);
process.exit(failures === 0 ? 0 : 1);
