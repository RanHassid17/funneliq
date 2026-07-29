/* FunnelIQ dashboard.
 *
 * The browser holds only the PUBLIC anon key and the session JWT Supabase issued
 * it. Every data request goes to our API with that token attached; the API
 * verifies the signature server-side and holds the service-role key. Nothing
 * privileged is reachable from this file.
 *
 * Session handling is the part the brief actually grades: an unauthenticated
 * visitor is redirected to the login screen before any panel renders, and
 * signing out clears the session and returns them there.
 */

(async () => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const money = (n) => "₪" + Math.round(n).toLocaleString();
  const pct = (n) => (n * 100).toFixed(1) + "%";

  // --- Session --------------------------------------------------------------

  const config = await fetch("/api/config").then((r) => r.json());
  const client = window.supabase.createClient(config.supabaseUrl, config.supabaseAnonKey);

  const { data: sessionData } = await client.auth.getSession();
  if (!sessionData.session) {
    // Gate the page before anything renders. A logged-out visitor must never
    // see the dashboard shell, let alone data.
    window.location.replace("/");
    return;
  }

  $("who").textContent = sessionData.session.user.email ?? "";

  $("signout").addEventListener("click", async () => {
    await client.auth.signOut();
    window.location.replace("/");
  });

  // Supabase refreshes tokens in the background; if the session ends for any
  // reason, drop back to the login screen rather than firing doomed requests.
  client.auth.onAuthStateChange((event, session) => {
    if (!session) window.location.replace("/");
  });

  async function api(path, options = {}) {
    const { data } = await client.auth.getSession();
    if (!data.session) {
      window.location.replace("/");
      throw new Error("Session ended");
    }
    const response = await fetch(path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        Authorization: "Bearer " + data.session.access_token,
        ...(options.headers || {}),
      },
    });
    const body = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(body.detail ? JSON.stringify(body.detail) : `Request failed (${response.status})`);
    }
    return body;
  }

  const setState = (id, text, kind = "") => {
    $(id).innerHTML = `<p class="state ${kind}">${text}</p>`;
  };

  // --- Predictions ----------------------------------------------------------

  function campaignInput() {
    const leads = Number($("num_leads").value) || 0;
    const answered = Number($("leads_answered").value) || 0;
    return {
      ad_budget: Number($("ad_budget").value) || 0,
      num_leads: leads,
      leads_answered: answered,
      leads_not_answered: Math.max(leads - answered, 0),
      followup_1: Number($("followup_1").value) || 0,
      followup_2: Number($("followup_2").value) || 0,
    };
  }

  const esc = (text) =>
    String(text).replace(/[&<>"']/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]
    );

  function provenance(result) {
    // An extrapolation warning goes ABOVE the provenance line and in the loud
    // style, because it changes whether the number should be believed at all.
    // Phase 7 found a zero-lead campaign returning a confident 33.66 months;
    // the number is still shown, but never again bare.
    const warning = result.in_distribution === false && result.warning
      ? `<div class="callout warn">${esc(result.warning)}</div>`
      : "";
    return (
      warning +
      `<p class="provenance">Model: ${esc(result.model)} · checkpoint ${esc(result.checkpoint)}${
        result.note ? "<br>" + esc(result.note) : ""
      }</p>`
    );
  }

  async function predictAll() {
    const payload = campaignInput();
    const message = $("predict-message");
    message.textContent = "";
    message.className = "message";

    const panels = [
      ["ltv-body", "/api/predict/ltv", renderLtv],
      ["upsell-body", "/api/predict/upsell", renderUpsell],
      ["referral-body", "/api/predict/referral-score", renderReferral],
      ["profit-body", "/api/predict/profit", renderProfit],
    ];
    panels.forEach(([id]) => setState(id, "Predicting…"));

    await Promise.all(
      panels.map(async ([id, path, render]) => {
        try {
          render(await api(path, { method: "POST", body: JSON.stringify(payload) }));
        } catch (error) {
          setState(id, error.message, "error");
          message.textContent = "Some predictions failed. Check the inputs describe a possible funnel.";
          message.className = "message error";
        }
      })
    );
  }

  const renderLtv = (r) =>
    ($("ltv-body").innerHTML =
      `<div class="big">${r.predicted_ltv_months} <span style="font-size:15px;color:var(--muted)">months</span></div>` +
      provenance(r));

  const renderUpsell = (r) =>
    ($("upsell-body").innerHTML =
      `<div class="big">${pct(r.upsell_probability)}</div>
       <div class="gauge"><div style="width:${r.upsell_probability * 100}%"></div></div>
       <div class="metric"><span class="k">Verdict</span><span class="v">${r.likely ? "Likely" : "Unlikely"}</span></div>` +
      provenance(r));

  const renderReferral = (r) =>
    ($("referral-body").innerHTML =
      `<div class="big">${r.referral_score}<span style="font-size:15px;color:var(--muted)"> / 100</span></div>
       <div class="gauge"><div style="width:${r.referral_score}%"></div></div>` +
      provenance(r));

  const renderProfit = (r) =>
    ($("profit-body").innerHTML =
      `<div class="big">${money(r.predicted_cumulative_profit)}</div>` + provenance(r));

  $("predict").addEventListener("click", predictAll);

  // --- Funnel dropout -------------------------------------------------------

  async function loadFunnel() {
    try {
      const data = await api("/api/funnel/dropout");
      const max = Math.max(...data.stages.map((s) => s.dropout_from_previous || 0));

      const bars = data.stages
        .map((stage) => {
          const dropout = stage.dropout_from_previous ?? 0;
          const kind =
            stage.stage === data.most_retentive_stage
              ? "best"
              : stage.stage === data.largest_dropout_stage
              ? "worst"
              : "";
          return `<div class="bar-row">
            <span class="bar-label">${stage.stage.replace("followup_", "Follow-up ")}</span>
            <span class="bar-track"><span class="bar-fill ${kind}" style="width:${(dropout / max) * 100}%"></span></span>
            <span class="bar-value">${pct(dropout)}</span>
          </div>`;
        })
        .join("");

      $("funnel-body").innerHTML = bars + `<div class="callout">${data.recommendation}</div>`;
    } catch (error) {
      setState("funnel-body", error.message, "error");
    }
  }

  // --- Budget simulator -----------------------------------------------------

  async function simulate() {
    setState("budget-body", "Simulating…");
    try {
      const data = await api("/api/budget/simulate", {
        method: "POST",
        body: JSON.stringify({ monthly_budget: Number($("monthly_budget").value) || 50000 }),
      });

      const rows = data.scenarios
        .map((s) => {
          const recommended = s.label === data.recommended.label;
          const flag = s.in_distribution
            ? recommended
              ? '<span class="tag good">recommended</span>'
              : ""
            : '<span class="tag warn">extrapolated</span>';
          return `<tr class="${recommended ? "highlight" : ""}">
            <td>${s.campaigns} × ${money(s.budget_per_campaign)}</td>
            <td class="${s.in_distribution ? "" : "excluded"}">${money(s.predicted_total_profit)}</td>
            <td class="${s.in_distribution ? "" : "excluded"}">${s.return_on_ad_spend.toFixed(2)}</td>
            <td>${flag}</td>
          </tr>`;
        })
        .join("");

      $("budget-body").innerHTML =
        `<div class="scroll-x"><table>
           <thead><tr><th>Strategy</th><th>Predicted profit</th><th>ROAS</th><th></th></tr></thead>
           <tbody>${rows}</tbody>
         </table></div>` +
        `<div class="callout"><strong>Recommended: ${data.recommended.label}</strong><br>${data.caveats.join("<br>")}</div>`;
    } catch (error) {
      setState("budget-body", error.message, "error");
    }
  }

  $("simulate").addEventListener("click", simulate);

  // --- Campaign comparison --------------------------------------------------

  async function loadCampaignOptions() {
    try {
      const data = await api("/api/campaigns?limit=100");
      if (!data.campaigns.length) {
        setState("compare-body", "No campaigns found.", "error");
        return;
      }
      const options = data.campaigns
        .map((c) => `<option value="${c.campaign_id}">${c.campaign_id} — ${money(c.ad_budget)}</option>`)
        .join("");
      $("cmp-a").innerHTML = options;
      $("cmp-b").innerHTML = options;
      $("cmp-b").selectedIndex = Math.min(1, data.campaigns.length - 1);
    } catch (error) {
      setState("compare-body", error.message, "error");
    }
  }

  async function compare() {
    const a = $("cmp-a").value;
    const b = $("cmp-b").value;
    if (a === b) return setState("compare-body", "Pick two different campaigns.", "error");

    setState("compare-body", "Comparing…");
    try {
      const data = await api(`/api/campaigns/compare?a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`);
      const names = Object.keys(data.delta_b_minus_a);

      const rows = names
        .map((name) => {
          const left = data.a.metrics[name];
          const right = data.b.metrics[name];
          const delta = data.delta_b_minus_a[name];
          const fmt = (v) => (v === null || v === undefined ? "—" : v.toFixed(3));
          const colour = delta > 0 ? "var(--good)" : delta < 0 ? "var(--bad)" : "var(--muted)";
          return `<tr>
            <td>${name.replace(/_/g, " ")}</td>
            <td>${fmt(left)}</td>
            <td>${fmt(right)}</td>
            <td style="color:${colour}">${delta > 0 ? "+" : ""}${fmt(delta)}</td>
          </tr>`;
        })
        .join("");

      $("compare-body").innerHTML = `<div class="scroll-x"><table>
        <thead><tr><th>Metric</th><th>${data.a.campaign_id}</th><th>${data.b.campaign_id}</th><th>Δ</th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>`;
    } catch (error) {
      setState("compare-body", error.message, "error");
    }
  }

  $("compare").addEventListener("click", compare);

  // --- Models in service ----------------------------------------------------

  async function loadModels() {
    try {
      const data = await api("/api/models");
      const rows = data.models
        .filter((m) => m.available)
        .map((m) => {
          // Show the honest scoreline: the headline metric AND what the naive
          // baseline scored, so a model that merely ties is visible as such.
          const key = "r2" in m.metrics ? "r2" : "f1";
          const model = m.metrics[key];
          const base = m.baseline_metrics[key] ?? 0;
          const delta = model - base;
          const verdict =
            delta > 0.01 ? '<span class="tag good">beats baseline</span>' : '<span class="tag warn">ties baseline</span>';
          return `<tr>
            <td>${m.target}</td>
            <td>${m.algorithm.length > 34 ? m.algorithm.slice(0, 34) + "…" : m.algorithm}</td>
            <td>${m.checkpoint}</td>
            <td>${key.toUpperCase()} ${model.toFixed(4)}</td>
            <td>${base.toFixed(4)}</td>
            <td>${verdict}</td>
          </tr>`;
        })
        .join("");

      $("models-body").innerHTML = `<div class="scroll-x"><table>
        <thead><tr><th>Target</th><th>Model</th><th>Checkpoint</th><th>Score</th><th>Baseline</th><th></th></tr></thead>
        <tbody>${rows}</tbody>
      </table></div>
      <div class="callout">Campaign lifetime and pre-launch profit are served by the budget
      baseline, because gradient boosting did not beat it. Reporting that is more useful than
      shipping a slower model with the same accuracy.</div>`;
    } catch (error) {
      setState("models-body", error.message, "error");
    }
  }

  // --- Ask the analyst ------------------------------------------------------

  async function loadAskPanel() {
    try {
      const status = await api("/api/ask/status");
      if (!status.available) return; // stays hidden; the reason is in /ready
      $("ask-panel").hidden = false;
      setState("ask-body", `Ask a question. Up to ${status.questions_per_hour} per hour — each one calls a paid model.`);
    } catch {
      // The analyst is optional. A dashboard that renders every other panel is
      // the right outcome when it is unreachable.
    }
  }

  async function ask() {
    const question = $("question").value.trim();
    if (!question) return;
    setState("ask-body", "Thinking… the analyst calls tools and a reviewer checks the draft, so this takes a few seconds.");
    $("ask").disabled = true;
    try {
      const data = await api("/api/ask", {
        method: "POST",
        body: JSON.stringify({ question }),
      });
      // The answer is model-generated text derived from campaign data, so it is
      // rendered as TEXT, never as markup. Building it into innerHTML would make
      // the analyst an injection path into the page.
      const body = $("ask-body");
      body.innerHTML = "";
      const answer = document.createElement("p");
      answer.className = "answer";
      answer.textContent = data.answer;
      body.appendChild(answer);

      if (data.campaign_language_warnings?.length) {
        const warning = document.createElement("div");
        warning.className = "callout warn";
        warning.textContent =
          "This answer used customer-level phrasing (" +
          data.campaign_language_warnings.join(", ") +
          "). FunnelIQ predicts campaign outcomes, not individual customers'.";
        body.appendChild(warning);
      }

      const note = document.createElement("p");
      note.className = "hint";
      note.textContent = data.note;
      body.appendChild(note);
    } catch (error) {
      setState("ask-body", error.message, "error");
    } finally {
      $("ask").disabled = false;
    }
  }

  $("ask").addEventListener("click", ask);
  $("question").addEventListener("keydown", (event) => {
    if (event.key === "Enter") ask();
  });

  // --- Boot -----------------------------------------------------------------

  await Promise.all([loadFunnel(), simulate(), loadCampaignOptions(), loadModels(), loadAskPanel()]);
  await predictAll();
})();
