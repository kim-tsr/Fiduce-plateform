"use strict";
// Dashboard de réconciliation. Protégé : sans session valide -> retour au login.

(async function guard() {
  if (!token()) { location.replace("/"); return; }
  try {
    await api("/auth/userinfo"); // valide le token avant d'afficher quoi que ce soit
  } catch (_) {
    location.replace("/");
    return;
  }
  const who = sessionStorage.getItem("fiduce_who") || "";
  $("#who").textContent = who;
  $("#avatar").textContent = (who.trim()[0] || "?").toUpperCase();
  attachEvents();
  refreshAll();
})();

const STATUS_LABEL = { pending: "En attente", matched: "Rapprochée", unmatched: "Non rapprochée" };

// --- Chargement des données --------------------------------------------------

async function loadAccounts() {
  const accounts = await api("/ledger/accounts");
  const tbody = $("#accounts-table tbody");
  const select = $("#entry-account");
  tbody.innerHTML = "";
  select.innerHTML = "";
  let total = 0;
  let currency = "EUR";
  for (const a of accounts) {
    select.insertAdjacentHTML("beforeend", `<option value="${a.code}">${a.code} — ${a.name}</option>`);
    let balance = "…";
    try {
      const b = await api(`/ledger/accounts/${a.code}/balance`);
      balance = fmtMoney(b.balance_cents, b.currency);
      total += b.balance_cents;
      currency = b.currency || currency;
    } catch (_) {}
    tbody.insertAdjacentHTML(
      "beforeend",
      `<tr><td class="mono">${a.code}</td><td>${a.name}</td><td class="num">${balance}</td></tr>`
    );
  }
  $("#kpi-balance").textContent = fmtMoney(total, currency);
}

async function loadEntries() {
  const entries = await api("/ledger/entries");
  const tbody = $("#entries-table tbody");
  tbody.innerHTML = "";
  const counts = { matched: 0, unmatched: 0, pending: 0 };
  if (!entries.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="empty">Aucune écriture. Enregistrez-en une pour commencer.</td></tr>`;
  } else {
    for (const e of entries) {
      counts[e.status] = (counts[e.status] || 0) + 1;
      tbody.insertAdjacentHTML(
        "beforeend",
        `<tr>
          <td class="mono">${e.account_code}</td>
          <td>${e.side === "debit" ? "Débit" : "Crédit"}</td>
          <td class="num">${fmtMoney(e.amount_cents, e.currency)}</td>
          <td class="mono">${e.reference || "—"}</td>
          <td class="mono">${e.external_ref || "—"}</td>
          <td><span class="status status-${e.status}">${STATUS_LABEL[e.status] || e.status}</span></td>
        </tr>`
      );
    }
  }
  $("#kpi-matched").textContent = counts.matched;
  $("#kpi-unmatched").textContent = counts.unmatched;
  $("#kpi-pending").textContent = counts.pending;
}

async function loadReports() {
  const reports = await api("/reporting/reports");
  const tbody = $("#reports-table tbody");
  tbody.innerHTML = "";
  if (!reports.length) {
    tbody.innerHTML = `<tr><td colspan="4" class="empty">Aucun rapport demandé.</td></tr>`;
    return;
  }
  for (const r of reports) {
    const when = new Date(r.requested_at).toLocaleString("fr-FR");
    const action = r.status === "ready"
      ? `<button class="ghost small" data-report="${r.id}">Voir</button>`
      : "";
    tbody.insertAdjacentHTML(
      "beforeend",
      `<tr>
        <td>${r.type}</td>
        <td><span class="status status-${r.status}">${r.status}</span></td>
        <td>${when}</td><td>${action}</td>
      </tr>`
    );
  }
  $$("[data-report]", tbody).forEach((btn) =>
    btn.addEventListener("click", async () => {
      const r = await api(`/reporting/reports/${btn.dataset.report}`);
      const pre = $("#report-result");
      pre.textContent = JSON.stringify(r.result, null, 2);
      pre.hidden = false;
      pre.scrollIntoView({ behavior: "smooth", block: "nearest" });
    })
  );
}

function refreshAll() {
  loadAccounts();
  loadEntries();
  loadReports();
}

// --- Actions -----------------------------------------------------------------

async function onCreateEntry(e) {
  e.preventDefault();
  const form = e.target;
  const f = new FormData(form);
  const msg = $("#entry-msg");
  msg.hidden = true;
  try {
    await api("/ledger/entries", {
      method: "POST",
      body: {
        account_code: f.get("account_code"),
        amount_cents: Number(f.get("amount_cents")),
        side: f.get("side"),
        reference: f.get("reference") || null,
        external_ref: f.get("external_ref") || null,
      },
    });
    msg.textContent = "Écriture enregistrée.";
    msg.className = "msg ok";
    msg.hidden = false;
    form.reset();
    await Promise.all([loadEntries(), loadAccounts()]);
  } catch (ex) {
    msg.textContent = ex.message;
    msg.className = "msg error";
    msg.hidden = false;
  }
}

async function onReconcile() {
  const badge = $("#reconcile-status");
  badge.hidden = false;
  badge.className = "badge running";
  badge.textContent = "Réconciliation en cours…";
  try {
    const { run_id } = await api("/ledger/reconcile", { method: "POST" });
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 800));
      const run = await api(`/ledger/reconcile/${run_id}`);
      if (run.status === "completed") {
        badge.className = "badge done";
        badge.textContent = `${run.matched_count} rapprochées · ${run.unmatched_count} non rapprochées`;
        await Promise.all([loadEntries(), loadAccounts()]);
        return;
      }
      if (run.status === "failed") {
        badge.className = "badge error";
        badge.textContent = "Échec de la réconciliation";
        return;
      }
    }
    badge.textContent = "Toujours en cours… (worker indisponible ?)";
  } catch (ex) {
    badge.className = "badge error";
    badge.textContent = ex.message;
  }
}

async function onReport(e) {
  e.preventDefault();
  const type = new FormData(e.target).get("type");
  try {
    const { report_id } = await api("/reporting/reports", { method: "POST", body: { type } });
    await loadReports();
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 800));
      const r = await api(`/reporting/reports/${report_id}`);
      if (r.status === "ready" || r.status === "failed") {
        await loadReports();
        return;
      }
    }
  } catch (ex) {
    alert(ex.message);
  }
}

function attachEvents() {
  $("#logout").addEventListener("click", logout);
  $("#refresh-accounts").addEventListener("click", loadAccounts);
  $("#refresh-all").addEventListener("click", refreshAll);
  $("#entry-form").addEventListener("submit", onCreateEntry);
  $("#reconcile-btn").addEventListener("click", onReconcile);
  $("#report-form").addEventListener("submit", onReport);
  // Surlignage de la navigation selon la section visible.
  const items = $$(".nav-item");
  const byId = new Map(items.map((a) => [a.getAttribute("href").slice(1), a]));
  const obs = new IntersectionObserver((entries) => {
    for (const en of entries) {
      if (en.isIntersecting && byId.has(en.target.id)) {
        items.forEach((x) => x.classList.remove("is-active"));
        byId.get(en.target.id).classList.add("is-active");
      }
    }
  }, { rootMargin: "-40% 0px -55% 0px" });
  ["comptes", "ecritures", "rapports"].forEach((id) => {
    const el = document.getElementById(id);
    if (el) obs.observe(el);
  });
}
