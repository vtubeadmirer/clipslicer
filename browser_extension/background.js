// ClipSlicer 연결 — 탭에서 오가는 HLS 재생 목록(m3u8) 요청을 요청 헤더(쿠키·인증 포함)와 함께 기억해 둔다.
// 아무것도 밖으로 보내지 않는다. 사용자가 팝업에서 버튼을 눌렀을 때만 이 PC 의 ClipSlicer(127.0.0.1)로 보낸다.

const MAX_PER_TAB = 15;
const DROP_HEADERS = new Set(["range", "if-none-match", "if-modified-since", "if-range", "accept-encoding", "content-length", "host", "connection"]);
const pending = new Map();  // requestId → {url, headers, t}

function isPlaylistUrl(url) {
  try { return new URL(url).pathname.toLowerCase().endsWith(".m3u8"); } catch { return false; }
}

function isPlaylistType(headers) {
  const ct = (headers || []).find(h => h.name.toLowerCase() === "content-type");
  return !!ct && /mpegurl/i.test(ct.value || "");
}

// 서비스 워커가 대신 받은 요청은 tabId 가 -1 → 그 요청을 낸 사이트(initiator)의 탭으로 돌린다 (활성 탭 우선)
async function tabForRequest(d) {
  if (d.tabId >= 0) return d.tabId;
  if (!d.initiator || !/^https?:/.test(d.initiator)) return -1;
  try {
    const tabs = await chrome.tabs.query({ url: d.initiator + "/*" });
    if (!tabs.length) return -1;
    const active = tabs.find(t => t.active);
    return (active || tabs.sort((a, b) => (b.lastAccessed || 0) - (a.lastAccessed || 0))[0]).id;
  } catch {
    return -1;
  }
}

chrome.webRequest.onSendHeaders.addListener(d => {
  if (d.tabId < 0 && !d.initiator) return;
  const headers = {};
  for (const h of d.requestHeaders || []) {
    if (!DROP_HEADERS.has(h.name.toLowerCase()) && h.value !== undefined) headers[h.name] = h.value;
  }
  pending.set(d.requestId, { url: d.url, headers, t: Date.now() });
  if (pending.size > 300) {
    const old = Date.now() - 60000;
    for (const [k, v] of pending) if (v.t < old) pending.delete(k);
  }
}, { urls: ["<all_urls>"], types: ["xmlhttprequest", "media", "other"] }, ["requestHeaders", "extraHeaders"]);

chrome.webRequest.onResponseStarted.addListener(async d => {
  const req = pending.get(d.requestId);
  pending.delete(d.requestId);
  if (!req || d.statusCode >= 400) return;
  if (!isPlaylistUrl(d.url) && !isPlaylistType(d.responseHeaders)) return;
  const tabId = await tabForRequest(d);
  if (tabId < 0) return;
  d = { ...d, tabId };
  const key = "tab" + d.tabId;
  const got = (await chrome.storage.session.get(key))[key] || [];
  const base = d.url.split("?")[0];
  const list = got.filter(s => s.url.split("?")[0] !== base);
  list.unshift({ url: d.url, headers: req.headers, t: Date.now() });
  list.length = Math.min(list.length, MAX_PER_TAB);
  await chrome.storage.session.set({ [key]: list });
  chrome.action.setBadgeText({ tabId: d.tabId, text: String(list.length) });
  chrome.action.setBadgeBackgroundColor({ tabId: d.tabId, color: "#e53935" });
}, { urls: ["<all_urls>"], types: ["xmlhttprequest", "media", "other"] }, ["responseHeaders"]);

chrome.webRequest.onErrorOccurred.addListener(d => pending.delete(d.requestId), { urls: ["<all_urls>"] });

// 다른 페이지로 가면 그 탭의 목록을 비운다 (같은 페이지 안의 주소 변경은 유지)
chrome.tabs.onUpdated.addListener((tabId, info) => {
  if (info.status === "loading" && info.url) {
    chrome.storage.session.remove("tab" + tabId);
    chrome.action.setBadgeText({ tabId, text: "" });
  }
});
chrome.tabs.onRemoved.addListener(tabId => chrome.storage.session.remove("tab" + tabId));

// 단축키(기본 Alt+Shift+C): 이 탭의 방송을 ClipSlicer 가 녹화 중이면 '방금 지나간 N초' 클립
chrome.commands.onCommand.addListener(async command => {
  if (command !== "clip") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  let text = "✂";
  try {
    const r = await fetch("http://127.0.0.1:47851/clip", { method: "POST", headers: { "Content-Type": "application/json" },
                                                         body: JSON.stringify({ page: (tab && tab.url) || "" }) });
    if (!r.ok) text = "!";
  } catch {
    text = "!";   // ClipSlicer 가 꺼져 있음
  }
  if (tab) {
    chrome.action.setBadgeText({ tabId: tab.id, text });
    chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: text === "✂" ? "#2e7d32" : "#c62828" });
    setTimeout(async () => {   // 잠깐 보여 준 뒤 원래 숫자로
      const key = "tab" + tab.id;
      const list = (await chrome.storage.session.get(key))[key] || [];
      chrome.action.setBadgeText({ tabId: tab.id, text: list.length ? String(list.length) : "" });
      chrome.action.setBadgeBackgroundColor({ tabId: tab.id, color: "#e53935" });
    }, 2000);
  }
});
