// 팝업: 이 탭에서 잡힌 재생 목록을 보여 주고, 고른 것을 ClipSlicer(127.0.0.1)로 보낸다.
const SERVER = "http://127.0.0.1:47851";
const $ = id => document.getElementById(id);
let tab = null;
let connected = false;

function say(text) { $("msg").textContent = text; }

function label(url) {
  try {
    const u = new URL(url);
    const parts = u.pathname.split("/").filter(Boolean);
    return parts.slice(-2).join("/") || u.host;
  } catch { return url.slice(0, 60); }
}

function ago(t) {
  const s = Math.round((Date.now() - t) / 1000);
  return s < 60 ? s + "초 전" : Math.round(s / 60) + "분 전";
}

// 'sub.example.co.kr' → 'example.co.kr' (대략적인 등록 도메인: 로그인 쿠키가 보통 여기 걸려 있다)
function siteDomain(host) {
  const p = host.split(".");
  if (p.length <= 2) return host;
  const second = p[p.length - 2];
  const n = (p[p.length - 1].length === 2 && ["co", "or", "ne", "go", "ac", "com", "net", "org"].includes(second)) ? 3 : 2;
  return p.slice(-n).join(".");
}

async function siteCookies(url) {
  const all = [];
  const seen = new Set();
  const add = list => list.forEach(c => {
    const k = c.domain + "|" + c.path + "|" + c.name;
    if (!seen.has(k)) { seen.add(k); all.push(c); }
  });
  add(await chrome.cookies.getAll({ url }));
  try { add(await chrome.cookies.getAll({ domain: siteDomain(new URL(url).hostname) })); } catch {}
  return all.map(c => ({ domain: c.hostOnly ? c.domain : (c.domain.startsWith(".") ? c.domain : "." + c.domain),
                         path: c.path, secure: c.secure, expiry: Math.floor(c.expirationDate || 0),
                         name: c.name, value: c.value }));
}

async function send(payload, button) {
  if (button) button.disabled = true;
  try {
    const r = await fetch(SERVER + "/send", { method: "POST", headers: { "Content-Type": "application/json" },
                                             body: JSON.stringify(payload) });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || ("HTTP " + r.status));
    say("보냈습니다. ClipSlicer 창을 확인하세요.");
  } catch (e) {
    say("보내지 못했습니다: " + e.message + " — ClipSlicer 가 켜져 있는지 확인하세요.");
    if (button) button.disabled = false;
  }
}

async function ping() {
  const st = $("status");
  try {
    // POST 로 보내야 브라우저가 Origin(확장 ID)을 붙인다 — 서버는 Origin 이 우리 확장인 요청만 받는다
    const r = await fetch(SERVER + "/ping", { method: "POST", cache: "no-store" });
    const j = await r.json();
    connected = r.ok && j.app === "ClipSlicer";
    st.textContent = connected ? "ClipSlicer " + j.version + " 연결됨" : "ClipSlicer 응답이 이상합니다";
  } catch {
    connected = false;
    st.textContent = "ClipSlicer 가 꺼져 있습니다. 먼저 ClipSlicer 를 실행하세요.";
  }
  st.className = "status " + (connected ? "ok" : "bad");
}

async function render() {
  const box = $("streams");
  box.textContent = "";
  const key = "tab" + tab.id;
  const list = (await chrome.storage.session.get(key))[key] || [];
  const head = document.createElement("div");
  head.className = "tabtitle";
  head.textContent = tab.title || tab.url || "";
  head.title = tab.url || "";
  box.appendChild(head);
  if (!list.length) {
    const d = document.createElement("div");
    d.className = "hint";
    d.textContent = "아직 잡힌 영상 스트림이 없습니다.";
    box.appendChild(d);
    return;
  }
  // ClipSlicer 에게 각 목록이 무엇인지 물어본다 (브라우저 헤더 그대로 받아 봄). 꺼져 있으면 주소만 보여 준다.
  const infos = connected ? await Promise.all(list.map(s => probe(s))) : list.map(() => null);
  const items = list.map((s, i) => ({ s, info: infos[i] }));
  // '한 화질' 목록이 몇 p 인지: 같은 탭의 '전체 화질' 목록에 든 경로와 맞춰 본다
  const pathHeight = {};
  for (const it of items) for (const v of (it.info && it.info.variant_paths) || []) if (v.height) pathHeight[v.path] = v.height;
  for (const it of items) {
    if (it.info && it.info.kind === "media") {
      try { it.height = pathHeight[new URL(it.s.url).pathname] || 0; } catch { it.height = 0; }
    }
  }
  // 지금 페이지에서 잡힌 것인지 · 이 페이지의 영상 id 가 재생 목록 주소에 들어 있는지
  const cur = pageKey(tab.url);
  const ids = pageIds(tab.url);
  for (const it of items) {
    it.samePage = !it.s.page || pageKey(it.s.page) === cur;   // (예전 버전이 잡은 것은 페이지 정보가 없음)
    it.pageMatch = ids.some(id => it.s.url.includes(id));
  }
  const usable = it => it.info && !it.info.error && !it.info.drm && !it.info.audio_only;
  const score = it => (it.pageMatch ? 20 : 0) + (it.samePage ? 10 : 0) + (!usable(it) ? -5 :
    (it.info.kind === "master" ? 3 : 1) + (it.info.live ? 2 : 0) + (it.height || 0) / 10000) + it.s.t / 1e16;
  items.sort((a, b) => score(b) - score(a));
  const best = items.find(it => usable(it) && it.samePage) || items.find(usable);

  let olderShown = false;
  for (const it of items) {
    if (!it.samePage && !olderShown) {   // 새로고침 없이 넘어오기 전 페이지에서 잡힌 것은 아래에 흐리게
      olderShown = true;
      const h = document.createElement("div");
      h.className = "hint";
      h.textContent = "이전 페이지에서 잡힌 것 (지금 보는 영상이 아닐 수 있음)";
      box.appendChild(h);
    }
    const { s, info } = it;
    const row = document.createElement("div");
    row.className = "item" + (it.samePage ? "" : " older");
    const text = document.createElement("div");
    text.className = "name";
    const main = document.createElement("div");
    main.className = "main";
    const sub = document.createElement("div");
    sub.className = "sub";
    sub.textContent = label(s.url) + " · " + ago(s.t);
    sub.title = s.url;
    if (it === best) {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = "추천";
      main.appendChild(tag);
    }
    if (it.pageMatch) {
      const tag = document.createElement("span");
      tag.className = "tag page";
      tag.textContent = "이 페이지 영상";
      tag.title = "재생 목록 주소에 이 페이지의 영상 번호가 들어 있습니다";
      main.appendChild(tag);
    }
    main.appendChild(document.createTextNode(describeText(info, it.height)));
    text.append(main, sub);
    const b = document.createElement("button");
    b.textContent = "녹화/받기";
    b.disabled = !connected || !!(info && info.drm);
    if (it !== best) b.className = "secondary";
    b.onclick = () => send({ kind: "stream", url: s.url, headers: s.headers, page: tab.url, title: tab.title }, b);
    row.append(text, b);
    box.appendChild(row);
  }
}

function pageKey(url) {
  return (url || "").split("#")[0].replace(/\/+$/, "");
}

// 페이지 주소의 영상 번호 같은 긴 토큰 (예: rplay.live/play/6ad1fd501c71… → '6ad1fd501c71…')
function pageIds(url) {
  try {
    return new URL(url).pathname.split("/").filter(p => /^[A-Za-z0-9_-]{10,}$/.test(p));
  } catch { return []; }
}

function fmtDur(sec) {
  sec = Math.round(sec || 0);
  const h = Math.floor(sec / 3600), m = Math.floor(sec % 3600 / 60), s = sec % 60;
  return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(s).padStart(2, "0");
}

function describeText(info, height) {
  if (!info) return "종류 확인 안 됨 (ClipSlicer 를 켜거나 최신으로 업데이트)";
  if (info.drm) return "DRM 보호 — 받을 수 없음";
  if (info.error) return "확인 실패 — 토큰이 만료됐을 수 있음";
  const live = info.live === true ? "실시간" : info.live === false ? "다시보기" + (info.duration ? " " + fmtDur(info.duration) : "") : "";
  if (info.audio_only) return ["소리만", live].filter(Boolean).join(" · ");
  if (info.kind === "master") {
    const hs = info.heights;
    const q = hs.length > 1 ? hs[0] + "p~" + hs[hs.length - 1] + "p" : hs.length ? hs[0] + "p" : "여러 화질";
    return ["전체 화질 " + q, live].filter(Boolean).join(" · ");
  }
  return [(height ? height + "p " : "") + "한 화질", live].filter(Boolean).join(" · ");
}

async function probe(s) {
  try {
    const r = await fetch(SERVER + "/probe", { method: "POST", headers: { "Content-Type": "application/json" },
                                              body: JSON.stringify({ url: s.url, headers: s.headers }) });
    if (r.status === 404) return null;   // 확인 기능이 없는 예전 ClipSlicer
    return r.ok ? await r.json() : { error: "HTTP " + r.status };
  } catch (e) {
    return null;
  }
}

(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await ping();
  await render();
  const pb = $("page");
  pb.disabled = !connected || !/^https?:/.test(tab.url || "");
  pb.onclick = async () => send({ kind: "page", url: tab.url, title: tab.title, cookies: await siteCookies(tab.url) }, pb);
  const cb = $("clip");
  cb.disabled = !connected;
  cb.onclick = async () => {
    try {
      const r = await fetch(SERVER + "/clip", { method: "POST", headers: { "Content-Type": "application/json" },
                                               body: JSON.stringify({ page: tab.url }) });
      say(r.ok ? "✂ 클립을 요청했습니다. ClipSlicer 알림을 확인하세요 (녹화 중이어야 합니다)."
               : "클립 요청 실패 (HTTP " + r.status + ") — ClipSlicer 를 최신으로 업데이트하세요.");
    } catch (e) {
      say("ClipSlicer 가 꺼져 있습니다.");
    }
  };
})();
