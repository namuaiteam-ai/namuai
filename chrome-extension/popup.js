const $ = (id) => document.getElementById(id);

function send(msg) {
  return chrome.runtime.sendMessage(msg);
}

function statusLabel(status) {
  return { pending: "대기", generating: "생성 중", running: "생성 중", done: "완료", error: "실패" }[status] || status;
}

function badgeClass(status) {
  if (status === "done") return "done";
  if (status === "error") return "error";
  if (status === "generating" || status === "running") return "run";
  return "";
}

function escapeHtml(s) {
  const div = document.createElement("div");
  div.textContent = s || "";
  return div.innerHTML;
}

function renderState(state) {
  if (!state) return;
  if (state.serverUrl) $("serverUrl").value = state.serverUrl;
  if (state.jobId) $("jobId").value = state.jobId;
  $("btnStart").disabled = !state.jobId || state.running;
  $("btnStop").disabled = !state.running;

  const items = state.items || [];
  const counts = { pending: 0, done: 0, error: 0, running: 0 };
  items.forEach((it) => {
    if (it.status === "done") counts.done++;
    else if (it.status === "error") counts.error++;
    else if (it.status === "generating" || it.status === "running") counts.running++;
    else counts.pending++;
  });
  $("summary").innerHTML = `
    <span class="chip">대기 ${counts.pending}</span>
    <span class="chip run">진행 ${counts.running}</span>
    <span class="chip done">완료 ${counts.done}</span>
    <span class="chip error">실패 ${counts.error}</span>
  `;
  $("list").innerHTML = items
    .map(
      (it) => `
    <div class="item">
      <span class="name">${escapeHtml(it.name || "#" + it.id)}</span>
      <span class="badge ${badgeClass(it.status)}">${statusLabel(it.status)}</span>
    </div>`
    )
    .join("");

  $("statusLine").textContent = state.running ? "자동 생성 진행 중..." : "";
}

async function init() {
  const stored = await chrome.storage.local.get(["namuai_serverUrl", "namuai_jobId"]);
  $("serverUrl").value = stored.namuai_serverUrl || "http://localhost:5000";
  if (stored.namuai_jobId) $("jobId").value = stored.namuai_jobId;

  try {
    const res = await send({ type: "GET_STATE" });
    if (res && res.ok) renderState(res.state);
  } catch (e) {
    // background 아직 초기화 전이면 무시
  }
}

$("btnLoad").addEventListener("click", async () => {
  const serverUrl = $("serverUrl").value.trim().replace(/\/$/, "");
  const jobId = $("jobId").value.trim();
  if (!serverUrl || !jobId) {
    $("statusLine").textContent = "서버 주소와 Job ID를 입력하세요.";
    return;
  }

  chrome.storage.local.set({ namuai_serverUrl: serverUrl, namuai_jobId: jobId });
  $("statusLine").textContent = "불러오는 중...";
  $("btnLoad").disabled = true;
  try {
    const res = await send({ type: "LOAD_JOB", serverUrl, jobId });
    if (!res.ok) {
      $("statusLine").textContent = "오류: " + res.error;
      return;
    }
    $("statusLine").textContent = `${res.items.length}개 프롬프트를 불러왔습니다.`;
    const stateRes = await send({ type: "GET_STATE" });
    if (stateRes && stateRes.ok) renderState(stateRes.state);
  } catch (e) {
    $("statusLine").textContent = "오류: " + e.message;
  } finally {
    $("btnLoad").disabled = false;
  }
});

$("btnStart").addEventListener("click", async () => {
  $("statusLine").textContent = "Gemini 탭을 여는 중...";
  $("btnStart").disabled = true;
  try {
    const res = await send({ type: "START_JOB" });
    if (!res.ok) {
      $("statusLine").textContent = "오류: " + res.error;
      $("btnStart").disabled = false;
      return;
    }
    $("statusLine").textContent = "자동 생성을 시작했습니다.";
    $("btnStop").disabled = false;
  } catch (e) {
    $("statusLine").textContent = "오류: " + e.message;
    $("btnStart").disabled = false;
  }
});

$("btnStop").addEventListener("click", async () => {
  await send({ type: "STOP_JOB" });
  $("statusLine").textContent = "중지 요청을 보냈습니다.";
  $("btnStop").disabled = true;
  $("btnStart").disabled = false;
});

chrome.runtime.onMessage.addListener((msg) => {
  if (msg.type === "PROGRESS_UPDATE") renderState(msg.state);
});

init();
