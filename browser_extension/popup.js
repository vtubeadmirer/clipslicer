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
  // master/playlist 같은 이름을 위로 (보통 화질 선택이 들어 있는 대표 목록)
  list.sort((a, b) => (/master|playlist|index|manifest/i.test(label(b.url)) - /master|playlist|index|manifest/i.test(label(a.url))) || b.t - a.t);
  if (!list.length) {
    const d = document.createElement("div");
    d.className = "hint";
    d.textContent = "아직 잡힌 영상 스트림이 없습니다.";
    box.appendChild(d);
    return;
  }
  for (const s of list) {
    const row = document.createElement("div");
    row.className = "item";
    const name = document.createElement("span");
    name.className = "name";
    name.textContent = label(s.url);
    name.title = s.url;
    const age = document.createElement("span");
    age.className = "age";
    age.textContent = ago(s.t);
    const b = document.createElement("button");
    b.textContent = "녹화/받기";
    b.disabled = !connected;
    b.onclick = () => send({ kind: "stream", url: s.url, headers: s.headers, page: tab.url, title: tab.title }, b);
    row.append(name, age, b);
    box.appendChild(row);
  }
}

(async () => {
  [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  await ping();
  await render();
  const pb = $("page");
  pb.disabled = !connected || !/^https?:/.test(tab.url || "");
  pb.onclick = async () => send({ kind: "page", url: tab.url, title: tab.title, cookies: await siteCookies(tab.url) }, pb);
})();
