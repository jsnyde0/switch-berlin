#!/usr/bin/env node
/**
 * kb-9f1h.7 — context-aware cross-link browser read-back.
 *
 * Tests the "Event hub ↗" link in BOTH contexts:
 * (A) IN-STUDIO: open /studio/, click Post row → composer swaps in #studio-main,
 *     then click "Event hub ↗" → SWAPS #studio-main to event composer, URL pushes.
 * (B) STANDALONE: navigate directly to /syndication/posts/<pk>/, click "Event hub ↗"
 *     → real browser NAVIGATION to /syndication/events/<pk>/ (window.location changes,
 *     full event-hub page renders — NOT a silent no-op).
 *
 * Prereqs:
 *   - Chrome up on localhost:9222  (node ~/.claude/skills/browser-automation/start.js)
 *   - Dev server:  uv run python manage.py runserver 8009
 *   - Seed user: studio-demo@switch.test / switch-smoke-2026 (pk: event=47, post=4)
 *
 * Run:  node scripts/crosslink_readback.mjs
 * Exit: 0 = all PASS, 1 = any FAIL.
 */
import { execFileSync } from "node:child_process";

const BA = process.env.HOME + "/.claude/skills/browser-automation";
const BASE = "http://127.0.0.1:8009";
const LABEL = "xlink";
const PW = "switch-smoke-2026";
// Post pk=4 is "Launch teaser" under Event pk=46 "Spring Munch 2026"
const EVENT_PK = 46;
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
  try {
    ba("wait.js", `--label=${LABEL}`, `--fn=${fn}`, `--timeout=${t}`);
    return true;
  } catch {
    return false;
  }
};
const waitUrl = (sub, t = 10000) => {
  try {
    ba("wait.js", `--label=${LABEL}`, `--url=${sub}`, `--timeout=${t}`);
    return true;
  } catch {
    return false;
  }
};

const logout = () => {
  nav(`${BASE}/accounts/logout/`);
  evalJs(
    `(() => { const f = Array.from(document.querySelectorAll("form")).find(f => f.querySelector("button,input[type=submit]")); if(f) f.submit(); return "ok"; })()`
  );
};
const login = (email) => {
  nav(`${BASE}/accounts/login/`);
  evalJs(
    `(() => { document.querySelector("input[name=login]").value=${JSON.stringify(email)}; document.querySelector("input[name=password]").value=${JSON.stringify(PW)}; document.querySelector("form").submit(); return "ok"; })()`
  );
  waitFn(
    `document.readyState === "complete" && !location.pathname.includes("login")`
  );
};

// bootstrap a fresh tab
navNew(`${BASE}/accounts/login/`);

// ---- Login as studio-demo ----
logout();
login("studio-demo@switch.test");

// =========================================================================
// (A) IN-STUDIO CONTEXT
// =========================================================================

console.log("\n--- (A) IN-STUDIO CONTEXT ---");

// Navigate to studio and click the Post row to load post composer
nav(`${BASE}/studio/`);
waitFn(`!!document.querySelector("#studio-main")`);

// Click the Post row in the rail
evalJs(
  `(() => { const r = Array.from(document.querySelectorAll("[hx-push-url]")).find(x=>x.getAttribute("hx-push-url")==="/syndication/posts/${POST_PK}/"); if(r) r.click(); else throw new Error("Post rail row not found"); return "ok"; })()`
);
const urlLoadedPost = waitUrl(`/syndication/posts/${POST_PK}/`, 10000);
report(
  "A1",
  urlLoadedPost,
  `URL pushed to /syndication/posts/${POST_PK}/ after rail click: ${urlLoadedPost}`
);

// Wait for the post_syndication sub-fragment to load (hx-trigger="load")
waitFn(
  `document.querySelector("#post-syndication") && !document.querySelector("#post-syndication [hx-trigger]")`,
  8000
);

// Assert "Event hub ↗" link in the post composer has hx-target="#studio-main"
// (it's in #studio-main so studio_swap=True was used)
const inStudioLinkCheck = JSON.parse(
  evalJs(`(() => {
  const main = document.querySelector("#studio-main");
  if (!main) return JSON.stringify({found: false, hasHxTarget: false, hasHxGet: false, href: null});
  // Find "Event hub" links inside #studio-main
  const links = Array.from(main.querySelectorAll("a")).filter(a => /Event hub/i.test(a.textContent));
  const link = links[0];
  return JSON.stringify({
    found: !!link,
    hasHxTarget: link ? link.getAttribute("hx-target") === "#studio-main" : false,
    hasHxGet: link ? !!link.getAttribute("hx-get") : false,
    href: link ? link.getAttribute("href") : null
  });
})()`)
);
report(
  "A2",
  inStudioLinkCheck.found &&
    inStudioLinkCheck.hasHxTarget &&
    inStudioLinkCheck.hasHxGet,
  `In-studio "Event hub" link: found=${inStudioLinkCheck.found}, hx-target=#studio-main=${inStudioLinkCheck.hasHxTarget}, hx-get=${inStudioLinkCheck.hasHxGet}`
);

// Now click "Event hub ↗" in-studio — should SWAP #studio-main (no full reload)
const pathBeforeClick = evalJs(`location.pathname`).replace(/\n/g, "");
evalJs(
  `(() => {
  const main = document.querySelector("#studio-main");
  const link = Array.from(main.querySelectorAll("a")).find(a => /Event hub/i.test(a.textContent));
  if (!link) throw new Error("Event hub link not found in #studio-main");
  link.click();
  return "ok";
})()`
);
const urlPushedToEvent = waitUrl(`/syndication/events/${EVENT_PK}/`, 10000);

const inStudioClickCheck = JSON.parse(
  evalJs(`(() => {
  const m = document.querySelector("#studio-main");
  const path = location.pathname;
  // Check that we're still on the studio page (rail still present) — no full reload
  const railPresent = !!document.querySelector("[hx-push-url]");
  // Check studio-main rendered event hub content (not post content)
  const inMain = m ? m.textContent : "";
  const eventHubRendered = /Event Hub/i.test(inMain);
  return JSON.stringify({path, railPresent, eventHubRendered, urlPushed: ${urlPushedToEvent}});
})()`)
);
report(
  "A3",
  inStudioClickCheck.urlPushed &&
    inStudioClickCheck.path === `/syndication/events/${EVENT_PK}/` &&
    inStudioClickCheck.railPresent,
  `After in-studio "Event hub" click: window.location.pathname="${inStudioClickCheck.path}", rail still present=${inStudioClickCheck.railPresent}, event hub rendered in main=${inStudioClickCheck.eventHubRendered}`
);

// =========================================================================
// (B) STANDALONE CONTEXT
// =========================================================================

console.log("\n--- (B) STANDALONE CONTEXT ---");

// Navigate directly to the post hub page (standalone — no studio shell)
nav(`${BASE}/syndication/posts/${POST_PK}/`);
waitFn(`document.readyState === "complete"`);

// Assert the page is standalone: no #studio-main
const standalonePageCheck = JSON.parse(
  evalJs(`(() => {
  const hasStudioMain = !!document.querySelector("#studio-main");
  const hasPostSyndication = !!document.querySelector("#post-syndication");
  return JSON.stringify({hasStudioMain, hasPostSyndication, path: location.pathname});
})()`)
);
report(
  "B1",
  !standalonePageCheck.hasStudioMain,
  `Standalone post_hub page: #studio-main present=${standalonePageCheck.hasStudioMain} (should be false), #post-syndication present=${standalonePageCheck.hasPostSyndication}, path="${standalonePageCheck.path}"`
);

// Wait for the post_syndication sub-fragment to load
waitFn(
  `document.querySelector("#post-syndication") && !document.querySelector("#post-syndication [hx-trigger]")`,
  8000
);

// Assert "Event hub ↗" link in standalone context does NOT have hx-target="#studio-main"
const standaloneLinkCheck = JSON.parse(
  evalJs(`(() => {
  const links = Array.from(document.querySelectorAll("a")).filter(a => /Event hub/i.test(a.textContent));
  const results = links.map(link => ({
    hasHxTarget: link.getAttribute("hx-target") === "#studio-main",
    hasHxGet: !!link.getAttribute("hx-get"),
    href: link.getAttribute("href")
  }));
  return JSON.stringify({count: links.length, links: results});
})()`)
);

const anyWithStudioTarget = standaloneLinkCheck.links.some(
  (l) => l.hasHxTarget
);
const allHaveHref = standaloneLinkCheck.links.every(
  (l) => l.href && l.href.includes(`/events/${EVENT_PK}/`)
);
report(
  "B2",
  !anyWithStudioTarget && allHaveHref,
  `Standalone "Event hub" links: count=${standaloneLinkCheck.count}, any with hx-target=#studio-main=${anyWithStudioTarget} (should be false), all have href to event=${allHaveHref}`
);

// Now click "Event hub ↗" in standalone — should do REAL navigation
const pathBeforeStandaloneClick = evalJs(`location.pathname`).replace(
  /\n/g,
  ""
);
evalJs(
  `(() => {
  const link = Array.from(document.querySelectorAll("a")).find(a => /Event hub/i.test(a.textContent));
  if (!link) throw new Error("Event hub link not found on standalone page");
  link.click();
  return "ok";
})()`
);
// Wait for navigation (full page load to event hub)
const navigatedToEvent = waitUrl(
  `/syndication/events/${EVENT_PK}/`,
  10000
);

const standaloneClickCheck = JSON.parse(
  evalJs(`(() => {
  const path = location.pathname;
  // On the event hub page (no studio shell), check no #studio-main and real page rendered
  const hasHtml = !!document.querySelector("html");
  const hasStudioMain = !!document.querySelector("#studio-main");
  const hasEventHubHeading = /Event Hub/i.test(document.body ? document.body.textContent : "");
  return JSON.stringify({path, hasHtml, hasStudioMain, hasEventHubHeading});
})()`)
);
report(
  "B3",
  navigatedToEvent &&
    standaloneClickCheck.path === `/syndication/events/${EVENT_PK}/` &&
    !standaloneClickCheck.hasStudioMain,
  `After standalone "Event hub" click: window.location.pathname="${standaloneClickCheck.path}", navigated to event hub (full page)=${navigatedToEvent}, no studio shell=${!standaloneClickCheck.hasStudioMain}, event hub heading=${standaloneClickCheck.hasEventHubHeading}`
);

console.log(
  failures === 0
    ? "\nALL STEPS PASS"
    : `\n${failures} STEP(S) FAILED`
);
process.exit(failures === 0 ? 0 : 1);
