// namuai Gemini 자동화 - 백그라운드 서비스 워커
// 팝업 ↔ content.js 사이의 작업 상태를 중계하고, 다운로드/서버 리포트를 처리한다.

let state = { serverUrl: "", jobId: "", items: [], running: false, geminiTabId: null };

chrome.storage.local.get("namuai_state", (res) => {
  if (res.namuai_state) state = res.namuai_state;
});

function saveState() {
  chrome.storage.local.set({ namuai_state: state });
}

function broadcast(msg) {
  chrome.runtime.sendMessage(msg).catch(() => {});
}

async function fetchPrompts(serverUrl, jobId) {
  const res = await fetch(`${serverUrl.replace(/\/$/, "")}/api/jobs/${jobId}/prompts`);
  if (!res.ok) throw new Error(`서버 응답 오류 (${res.status})`);
  const data = await res.json();
  if (data.error) throw new Error(data.error);
  return data.items;
}

async function reportProgress(itemId, status, message) {
  try {
    await fetch(`${state.serverUrl.replace(/\/$/, "")}/api/jobs/${state.jobId}/report`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ id: itemId, status, message: message || "" }),
    });
  } catch (e) {
    // 서버 리포트 실패는 무시한다 - 다운로드 자체는 이미 완료된 상태
  }
}

async function ensureGeminiTab() {
  const tabs = await chrome.tabs.query({ url: "https://gemini.google.com/*" });
  if (tabs.length > 0) {
    await chrome.tabs.update(tabs[0].id, { active: true });
    return tabs[0].id;
  }
  const tab = await chrome.tabs.create({ url: "https://gemini.google.com/app" });
  await waitForTabComplete(tab.id);
  return tab.id;
}

function waitForTabComplete(tabId) {
  return new Promise((resolve) => {
    function listener(id, info) {
      if (id === tabId && info.status === "complete") {
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }
    chrome.tabs.onUpdated.addListener(listener);
    setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      resolve();
    }, 20000);
  });
}

async function sendToContentWithRetry(tabId, msg, retries = 10) {
  for (let i = 0; i < retries; i++) {
    try {
      return await chrome.tabs.sendMessage(tabId, msg);
    } catch (e) {
      await new Promise((r) => setTimeout(r, 1000));
    }
  }
  throw new Error("Gemini 페이지의 콘텐츠 스크립트에 연결할 수 없습니다. 페이지를 새로고침한 뒤 다시 시도하세요.");
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  (async () => {
    try {
      if (msg.type === "LOAD_JOB") {
        const items = await fetchPrompts(msg.serverUrl, msg.jobId);
        state.serverUrl = msg.serverUrl;
        state.jobId = msg.jobId;
        state.items = items;
        state.running = false;
        saveState();
        sendResponse({ ok: true, items });
      } else if (msg.type === "START_JOB") {
        if (!state.jobId) {
          sendResponse({ ok: false, error: "먼저 프롬프트를 불러오세요." });
          return;
        }
        const tabId = await ensureGeminiTab();
        state.geminiTabId = tabId;
        state.running = true;
        saveState();
        await sendToContentWithRetry(tabId, {
          type: "START", serverUrl: state.serverUrl, jobId: state.jobId, items: state.items,
        });
        sendResponse({ ok: true });
      } else if (msg.type === "STOP_JOB") {
        if (state.geminiTabId) {
          chrome.tabs.sendMessage(state.geminiTabId, { type: "STOP" }).catch(() => {});
        }
        state.running = false;
        saveState();
        sendResponse({ ok: true });
      } else if (msg.type === "GET_STATE") {
        sendResponse({ ok: true, state });
      } else if (msg.type === "PROGRESS") {
        const item = state.items.find((it) => it.id === msg.itemId);
        if (item) {
          item.status = msg.status;
          item.message = msg.message || "";
        }
        saveState();
        reportProgress(msg.itemId, msg.status, msg.message);
        broadcast({ type: "PROGRESS_UPDATE", state });
        sendResponse({ ok: true });
      } else if (msg.type === "JOB_DONE") {
        state.running = false;
        saveState();
        broadcast({ type: "PROGRESS_UPDATE", state });
        sendResponse({ ok: true });
      } else if (msg.type === "DOWNLOAD_IMAGE") {
        chrome.downloads.download(
          { url: msg.dataUrl, filename: `namuai-gemini/${msg.filename}`, saveAs: false },
          (downloadId) => {
            sendResponse({
              ok: !!downloadId,
              downloadId,
              error: chrome.runtime.lastError ? chrome.runtime.lastError.message : null,
            });
          }
        );
      } else if (msg.type === "HEARTBEAT") {
        sendResponse({ ok: true });
      } else {
        sendResponse({ ok: false, error: "unknown message type" });
      }
    } catch (e) {
      sendResponse({ ok: false, error: e.message });
    }
  })();
  return true; // 비동기 sendResponse를 위해 메시지 채널을 열어둔다
});
