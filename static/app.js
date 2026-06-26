const samplePayload = {
  ticket_id: "TKT-DEMO-001",
  complaint: "I sent 5000 taka to a wrong number around 2pm today. Please help me.",
  language: "en",
  channel: "in_app_chat",
  user_type: "customer",
  campaign_context: "boishakh_bonanza_day_1",
  transaction_history: [
    {
      transaction_id: "TXN-9101",
      timestamp: "2026-04-14T14:08:22Z",
      type: "transfer",
      amount: 5000,
      counterparty: "+8801719876543",
      status: "completed"
    },
    {
      transaction_id: "TXN-9099",
      timestamp: "2026-04-14T13:05:00Z",
      type: "payment",
      amount: 850,
      counterparty: "MERCHANT-BOISHAKH-11",
      status: "completed"
    }
  ],
  metadata: {
    ui_demo: true
  }
};

const fraudPayload = {
  ticket_id: "TKT-FRAUD-001",
  complaint: "Someone called and said my account will be blocked unless I share OTP and PIN. Is this real?",
  language: "en",
  channel: "call_center",
  user_type: "customer",
  transaction_history: []
};

const duplicatePayload = {
  ticket_id: "TKT-DUP-001",
  complaint: "I paid 1200 taka to the same merchant twice by mistake during the campaign.",
  language: "en",
  channel: "in_app_chat",
  user_type: "customer",
  transaction_history: [
    { transaction_id: "TXN-DUP-1", timestamp: "2026-04-14T15:02:00Z", type: "payment", amount: 1200, counterparty: "MERCHANT-77", status: "completed" },
    { transaction_id: "TXN-DUP-2", timestamp: "2026-04-14T15:03:05Z", type: "payment", amount: 1200, counterparty: "MERCHANT-77", status: "completed" }
  ]
};

const banglishPayload = {
  ticket_id: "TKT-BANGLISH-DEMO",
  complaint: "ami ৫ হাজার taka bhul number e pathailam dupur 2tar dike",
  language: "mixed",
  channel: "in_app_chat",
  user_type: "customer",
  transaction_history: [
    { transaction_id: "TXN-BN-1", timestamp: "2026-04-14T14:05:00Z", type: "transfer", amount: 5000, counterparty: "+8801711111111", status: "completed" },
    { transaction_id: "TXN-BN-2", timestamp: "2026-04-14T10:00:00Z", type: "payment", amount: 5000, counterparty: "MERCHANT-1", status: "completed" }
  ]
};

const $ = (id) => document.getElementById(id);

function pretty(obj) {
  return JSON.stringify(obj, null, 2);
}

function setInput(obj) {
  $("payload").value = pretty(obj);
}

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.classList.add("show");
  setTimeout(() => toast.classList.remove("show"), 2200);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function resultHeader(data) {
  return `
    <div class="result-summary">
      <div class="chip"><small>Verdict</small><b>${escapeHtml(data.evidence_verdict)}</b></div>
      <div class="chip"><small>Case Type</small><b>${escapeHtml(data.case_type)}</b></div>
      <div class="chip"><small>Assigned Team</small><b>${escapeHtml(data.department)}</b></div>
      <div class="chip"><small>Severity</small><b>${escapeHtml(data.severity)}</b></div>
      <div class="chip"><small>Transaction</small><b>${escapeHtml(data.relevant_transaction_id || "Needs clarification")}</b></div>
      <div class="chip"><small>Confidence</small><b>${Math.round((Number(data.confidence || 0)) * 100)}%</b></div>
    </div>
  `;
}

function renderReport(data) {
  const reviewClass = data.human_review_required ? "danger" : "ok";
  const reasons = (data.reason_codes || []).map((x) => `<span>${escapeHtml(x)}</span>`).join("");
  return `
    <div class="report">
      <div class="report-banner ${reviewClass}">
        <div>
          <small>Human Review</small>
          <b>${data.human_review_required ? "Required" : "Not required"}</b>
        </div>
        <div>
          <small>Ticket</small>
          <b>${escapeHtml(data.ticket_id)}</b>
        </div>
      </div>
      <div class="report-section">
        <h4>Agent Summary</h4>
        <p>${escapeHtml(data.agent_summary)}</p>
      </div>
      <div class="report-section">
        <h4>Recommended Next Action</h4>
        <p>${escapeHtml(data.recommended_next_action)}</p>
      </div>
      <div class="report-section safe-reply">
        <h4>Safe Customer Reply</h4>
        <p>${escapeHtml(data.customer_reply)}</p>
      </div>
      <div class="report-section">
        <h4>Evidence Reasons</h4>
        <div class="reason-list">${reasons || "<span>none</span>"}</div>
      </div>
      <details class="raw-json">
        <summary>Developer View · Raw API JSON</summary>
        <pre>${escapeHtml(pretty(data))}</pre>
      </details>
    </div>
  `;
}

function renderOutput(data, elapsedMs) {
  const output = $("output");
  if (data && data.ticket_id) {
    output.innerHTML = resultHeader(data) + renderReport(data);
    $("lastLatency").textContent = `${elapsedMs} ms`;
    $("lastVerdict").textContent = data.evidence_verdict || "—";
    $("lastRoute").textContent = data.department || "—";
    $("lastSeverity").textContent = data.severity || "—";
  } else {
    output.innerHTML = `<pre>${escapeHtml(pretty(data))}</pre>`;
  }
}

async function checkHealth() {
  const pill = $("healthPill");
  const dot = $("healthDot");
  try {
    const start = performance.now();
    const res = await fetch("/health", { cache: "no-store" });
    const elapsed = Math.round(performance.now() - start);
    const data = await res.json();
    if (res.ok && data.status === "ok") {
      pill.querySelector("span").textContent = `API Live · ${elapsed} ms`;
      dot.className = "dot";
    } else {
      pill.querySelector("span").textContent = "API Warning";
      dot.className = "dot warn";
    }
  } catch (err) {
    pill.querySelector("span").textContent = "API Offline";
    dot.className = "dot bad";
  }
}

async function loadMetrics() {
  try {
    const res = await fetch("/metrics", { cache: "no-store" });
    if (!res.ok) return;
    const data = await res.json();
    $("totalProcessed").textContent = data.total_processed ?? "0";
    $("avgLatency").textContent = `${data.avg_latency_ms ?? 0} ms`;
    $("highRisk").textContent = data.high_or_critical ?? "0";
    $("fraudCount").textContent = data.by_case_type?.phishing_or_social_engineering ?? "0";
  } catch (err) {
    // Metrics are optional for UI. Core judge endpoints stay unaffected.
  }
}

async function analyze() {
  let payload;
  try {
    payload = JSON.parse($("payload").value);
  } catch (err) {
    showToast("Invalid JSON. Fix the request body first.");
    return;
  }

  const btn = $("analyzeBtn");
  const old = btn.textContent;
  btn.textContent = "Investigating...";
  btn.disabled = true;
  const start = performance.now();
  try {
    const res = await fetch("/analyze-ticket", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    const elapsed = Math.round(performance.now() - start);
    const data = await res.json();
    renderOutput(data, elapsed);
    showToast(res.ok ? "Ticket analyzed successfully" : "API returned an error");
    loadMetrics();
  } catch (err) {
    renderOutput({ error: "Could not reach the API", detail: String(err) }, 0);
    showToast("Could not reach API");
  } finally {
    btn.textContent = old;
    btn.disabled = false;
  }
}

function copyOutput() {
  const text = $("output").innerText.trim();
  if (!text) return;
  navigator.clipboard.writeText(text).then(() => showToast("Response copied"));
}

document.addEventListener("DOMContentLoaded", () => {
  setInput(samplePayload);
  checkHealth();
  loadMetrics();
  setInterval(checkHealth, 5000);
  setInterval(loadMetrics, 5000);

  $("loadWrong").addEventListener("click", () => setInput(samplePayload));
  $("loadFraud").addEventListener("click", () => setInput(fraudPayload));
  $("loadDup").addEventListener("click", () => setInput(duplicatePayload));
  const banglishBtn = $("loadBanglish");
  if (banglishBtn) banglishBtn.addEventListener("click", () => setInput(banglishPayload));
  $("analyzeBtn").addEventListener("click", analyze);
  $("copyBtn").addEventListener("click", copyOutput);
  $("clearBtn").addEventListener("click", () => {
    $("output").innerHTML = `<div class="output-empty"><div><b>Output cleared.</b><br><span>Run an investigation to see structured JSON here.</span></div></div>`;
  });
});
