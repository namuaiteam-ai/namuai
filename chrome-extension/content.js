// namuai Gemini 자동화 - 콘텐츠 스크립트 (gemini.google.com에서 실행)
//
// Gemini 웹 UI의 DOM 구조는 구글이 언제든 변경할 수 있다.
// 아래 SELECTORS만 실제 페이지에 맞게 수정하면 나머지 로직은 그대로 재사용된다.
const SELECTORS = {
  input: [
    "rich-textarea .ql-editor",
    "div.ql-editor[contenteditable='true']",
    "div[contenteditable='true'][role='textbox']",
    "textarea",
  ],
  sendButton: [
    "button.send-button:not([disabled])",
    "button[aria-label='Send message' i]:not([disabled])",
    "button[aria-label*='보내기']:not([disabled])",
    "button[aria-label*='Submit' i]:not([disabled])",
  ],
};

// Gemini가 이미지 생성 요청으로 인식하도록 프롬프트 앞에 붙이는 문구
const PROMPT_PREFIX = "Generate an image: ";

const jobState = { running: false, stopRequested: false };

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function querySelectorFirst(selectors) {
  for (const sel of selectors) {
    const el = document.querySelector(sel);
    if (el) return el;
  }
  return null;
}

function waitFor(fn, timeoutMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const iv = setInterval(() => {
      const el = fn();
      if (el || Date.now() - start > timeoutMs) {
        clearInterval(iv);
        resolve(el || null);
      }
    }, 300);
  });
}

async function setPromptText(el, text) {
  el.focus();
  document.execCommand("selectAll", false, null);
  document.execCommand("delete", false, null);
  const ok = document.execCommand("insertText", false, text);
  if (!ok) {
    el.textContent = text;
    el.dispatchEvent(new InputEvent("input", { bubbles: true, data: text, inputType: "insertText" }));
  }
  await sleep(300);
}

function collectImageSrcSet() {
  return new Set(
    Array.from(document.querySelectorAll("img"))
      .map((img) => img.currentSrc || img.src)
      .filter(Boolean)
  );
}

function getNewGeneratedImages(beforeSet) {
  return Array.from(document.querySelectorAll("img")).filter((img) => {
    const src = img.currentSrc || img.src;
    if (!src || beforeSet.has(src)) return false;
    const w = img.naturalWidth || img.width;
    const h = img.naturalHeight || img.height;
    return w >= 200 && h >= 200; // 아이콘/아바타 등 작은 이미지는 제외
  });
}

function waitForGeneration(beforeSet, { maxWaitMs = 120000, idleMs = 1800, heartbeat } = {}) {
  return new Promise((resolve) => {
    let lastMutation = Date.now();
    const observer = new MutationObserver(() => {
      lastMutation = Date.now();
    });
    observer.observe(document.body, { childList: true, subtree: true, attributes: true });

    const start = Date.now();
    let lastHeartbeat = Date.now();
    const timer = setInterval(() => {
      const now = Date.now();
      if (heartbeat && now - lastHeartbeat > 8000) {
        heartbeat();
        lastHeartbeat = now;
      }

      const newImages = getNewGeneratedImages(beforeSet);
      const idle = now - lastMutation > idleMs;
      const timedOut = now - start > maxWaitMs;

      if ((newImages.length > 0 && idle) || timedOut) {
        clearInterval(timer);
        observer.disconnect();
        resolve({ images: newImages, timedOut: timedOut && newImages.length === 0 });
      }
    }, 500);
  });
}

function blobToDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onloadend = () => resolve(reader.result);
    reader.onerror = reject;
    reader.readAsDataURL(blob);
  });
}

async function downloadImage(src, filename) {
  let dataUrl;
  if (src.startsWith("data:")) {
    dataUrl = src;
  } else {
    const res = await fetch(src);
    const blob = await res.blob();
    dataUrl = await blobToDataUrl(blob);
  }
  return chrome.runtime.sendMessage({ type: "DOWNLOAD_IMAGE", dataUrl, filename });
}

function safeName(name) {
  return (name || "image").replace(/[\\/:*?"<>|]/g, "_").trim().slice(0, 60) || "image";
}

function report(itemId, status, message) {
  chrome.runtime.sendMessage({ type: "PROGRESS", itemId, status, message }).catch(() => {});
}

async function runJob(serverUrl, jobId, items) {
  jobState.running = true;
  jobState.stopRequested = false;

  for (const item of items) {
    if (jobState.stopRequested) break;
    if (item.status === "done") continue;

    report(item.id, "generating", "");

    const input = await waitFor(() => querySelectorFirst(SELECTORS.input), 15000);
    if (!input) {
      report(item.id, "error", "입력창을 찾을 수 없습니다. content.js의 SELECTORS.input을 확인하세요.");
      continue;
    }

    const beforeSet = collectImageSrcSet();
    await setPromptText(input, PROMPT_PREFIX + item.prompt);

    const sendBtn = await waitFor(() => querySelectorFirst(SELECTORS.sendButton), 5000);
    if (!sendBtn) {
      report(item.id, "error", "전송 버튼을 찾을 수 없습니다. content.js의 SELECTORS.sendButton을 확인하세요.");
      continue;
    }
    sendBtn.click();

    const { images, timedOut } = await waitForGeneration(beforeSet, {
      heartbeat: () => chrome.runtime.sendMessage({ type: "HEARTBEAT" }).catch(() => {}),
    });

    if (jobState.stopRequested) break;

    if (images.length === 0) {
      report(
        item.id,
        "error",
        timedOut ? "이미지 생성 대기 시간이 초과되었습니다." : "생성된 이미지를 찾지 못했습니다."
      );
      continue;
    }

    let downloaded = 0;
    for (let i = 0; i < images.length; i++) {
      const img = images[i];
      const src = img.currentSrc || img.src;
      const filename = `${jobId}/${safeName(item.name)}_${item.id}_${i + 1}.png`;
      try {
        const res = await downloadImage(src, filename);
        if (res && res.ok) downloaded++;
      } catch (e) {
        // 개별 이미지 다운로드 실패는 건너뛰고 나머지는 계속 진행
      }
    }

    if (downloaded > 0) {
      report(item.id, "done", `${downloaded}장 다운로드 완료`);
    } else {
      report(item.id, "error", "이미지 다운로드에 실패했습니다.");
    }

    await sleep(3000 + Math.random() * 3000);
  }

  jobState.running = false;
  chrome.runtime.sendMessage({ type: "JOB_DONE", jobId }).catch(() => {});
}

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === "START") {
    if (!jobState.running) runJob(msg.serverUrl, msg.jobId, msg.items);
    sendResponse({ ok: true });
  } else if (msg.type === "STOP") {
    jobState.stopRequested = true;
    sendResponse({ ok: true });
  }
  return true;
});
