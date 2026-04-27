const API = "https://volunteer-backend-rjo1.onrender.com/api";

// ─── UTILS ───────────────────────────────────────────────────

function spin() { return `<span class="spinner"></span>`; }

function badgeHTML(urgency) {
  const u = (urgency || "low").toLowerCase();
  return `<span class="badge badge-${u}">${u}</span>`;
}

async function apiFetch(path, options = {}) {
  try {
    const res = await fetch(API + path, options);
    return await res.json();
  } catch (e) {
    return { error: e.message };
  }
}

function showResult(box, type, html) {
  box.className = `result-box ${type}`;
  box.innerHTML = html;
}

// ─── TABS ─────────────────────────────────────────────────────

function switchTab(name) {
  document.querySelectorAll(".tab-content").forEach(t => t.classList.remove("active"));
  document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
  document.getElementById(`tab-${name}`).classList.add("active");
  event.target.classList.add("active");

  // Auto-load content when tab opens
  if (name === "dashboard") { loadSummary(); loadNeeds(); loadBurnout(); }
  if (name === "matches") loadMatches(false);
  if (name === "heatmap") loadHeatmap();
  if (name === "insights") loadInsights();
  if (name === "register-vol") loadVolunteers();
}

// ─── STATS BAR ────────────────────────────────────────────────

async function loadStats() {
  const data = await apiFetch("/needs");
  if (data.needs) {
    document.getElementById("totalNeeds").textContent = data.needs.filter(n => n.status !== "completed").length;
    document.getElementById("criticalCount").textContent = data.needs.filter(n => n.urgency === "critical" && n.status !== "completed").length;
    const people = data.needs.reduce((s, n) => s + (parseInt(n.people_affected) || 0), 0);
    document.getElementById("totalPeople").textContent = people.toLocaleString();
  }
  const vols = await apiFetch("/volunteers");
  if (vols.volunteers) {
    document.getElementById("totalVols").textContent = vols.count;
  }
}

// ─── SUBMIT NEED ──────────────────────────────────────────────

async function submitNeed() {
  const desc = document.getElementById("needDesc").value.trim();
  const resultBox = document.getElementById("needSubmitResult");
  const btnText = document.getElementById("submitNeedText");

  if (!desc) { showResult(resultBox, "error", "❌ Please describe the need."); return; }

  btnText.innerHTML = `${spin()} Gemini is analyzing...`;
  document.querySelector("#tab-submit-need .btn-primary").disabled = true;

  const data = await apiFetch("/needs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      ngo_name: document.getElementById("ngoName").value,
      contact: document.getElementById("contactName").value,
      description: desc,
      location: document.getElementById("needLocation").value,
      lat: parseFloat(document.getElementById("needLat").value) || 0,
      lng: parseFloat(document.getElementById("needLng").value) || 0
    })
  });

  document.querySelector("#tab-submit-need .btn-primary").disabled = false;
  btnText.textContent = "⚡ Parse & Submit with Gemini AI";

  if (data.success) {
    const n = data.need;
    const source = data.parsed_by === "gemini" ? "🤖 Gemini AI" : "🤖 Gemini AI";
    showResult(resultBox, "success",
      `✅ <strong>Need submitted successfully!</strong><br>
       Parsed by: ${source}<br>
       <strong>Category:</strong> ${n.category} &nbsp;|&nbsp;
       <strong>Urgency:</strong> ${n.urgency} &nbsp;|&nbsp;
       <strong>People:</strong> ${n.people_affected}<br>
       <strong>Priority Score:</strong> ${n.priority_score}/100<br>
       <em>"${data.gemini_summary}"</em>`
    );
    document.getElementById("needDesc").value = "";
    loadStats();
  } else {
    showResult(resultBox, "error", `❌ Error: ${data.error}`);
  }
}

// ─── REGISTER VOLUNTEER ───────────────────────────────────────

async function registerVolunteer() {
  const name = document.getElementById("volName").value.trim();
  const resultBox = document.getElementById("volSubmitResult");
  const btnText = document.getElementById("submitVolText");

  if (!name) { showResult(resultBox, "error", "❌ Name is required."); return; }

  // Combine typed skills + checkboxes
  const typed = document.getElementById("volSkills").value;
  const checked = Array.from(document.querySelectorAll("#skillCheckboxes input:checked"))
    .map(cb => cb.value);
  const allSkills = [...new Set([typed, ...checked].filter(Boolean).join(", ").split(", ").filter(Boolean))].join(", ");

  btnText.innerHTML = `${spin()} Registering...`;
  document.querySelector("#tab-register-vol .btn-primary").disabled = true;

  const data = await apiFetch("/volunteers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      name,
      phone: document.getElementById("volPhone").value,
      skills: allSkills,
      location: document.getElementById("volLocation").value,
      lat: parseFloat(document.getElementById("volLat").value) || 0,
      lng: parseFloat(document.getElementById("volLng").value) || 0,
      availability: document.getElementById("volAvailability").value,
      max_capacity: parseInt(document.getElementById("volCapacity").value) || 2
    })
  });

  document.querySelector("#tab-register-vol .btn-primary").disabled = false;
  btnText.textContent = "✅ Register Volunteer";

  if (data.success) {
    showResult(resultBox, "success",
      `✅ <strong>${data.volunteer.name}</strong> registered successfully!<br>
       Skills: ${data.volunteer.skills}<br>
       Location: ${data.volunteer.location}`
    );
    document.getElementById("volName").value = "";
    document.getElementById("volPhone").value = "";
    document.getElementById("volSkills").value = "";
    document.querySelectorAll("#skillCheckboxes input").forEach(cb => cb.checked = false);
    loadVolunteers();
    loadStats();
  } else {
    showResult(resultBox, "error", `❌ Error: ${data.error}`);
  }
}

// ─── NEEDS LIST ───────────────────────────────────────────────

async function loadNeeds() {
  const container = document.getElementById("needsList");
  container.innerHTML = `<div class="loading-state">${spin()} Loading needs...</div>`;
  const data = await apiFetch("/needs");
  if (!data.needs || data.needs.length === 0) {
    container.innerHTML = `<div class="loading-state">No active needs. Submit one from the "Submit Need" tab.</div>`;
    return;
  }
  const active = data.needs.filter(n => n.status !== "completed");
  container.innerHTML = active.map(n => `
    <div class="need-item need-${(n.urgency||'low').toLowerCase()}">
      <div class="need-item-header">
        ${badgeHTML(n.urgency)}
        <span class="badge" style="background:#e0f2fe;color:#0369a1">${n.category||'—'}</span>
        <span class="priority-chip">Score: ${n.priority_score||'—'}</span>
        <span class="badge" style="background:#f1f5f9;color:#64748b">${n.status||'pending'}</span>
      </div>
      <div class="need-item-desc">${n.description||'No description'}</div>
      <div class="need-item-meta">
        📍 ${n.location||'Unknown'} &nbsp;·&nbsp; 
        👥 ${n.people_affected||'?'} people &nbsp;·&nbsp;
        🏢 ${n.ngo_name||'NGO'} &nbsp;·&nbsp;
        🆔 ${n.id}
      </div>
    </div>`).join("");
}

// ─── VOLUNTEERS TABLE ─────────────────────────────────────────

async function loadVolunteers() {
  const container = document.getElementById("volunteersTable");
  container.innerHTML = `<div class="loading-state">${spin()} Loading...</div>`;
  const data = await apiFetch("/volunteers");
  if (!data.volunteers || data.volunteers.length === 0) {
    container.innerHTML = `<div class="loading-state">No volunteers yet. Register one above.</div>`;
    return;
  }
  container.innerHTML = `
    <table class="vol-table">
      <thead><tr>
        <th>Name</th><th>Skills</th><th>Location</th>
        <th>Availability</th><th>Workload</th>
      </tr></thead>
      <tbody>
        ${data.volunteers.map(v => `
          <tr>
            <td><strong>${v.name}</strong><br><span style="font-size:0.75rem;color:#64748b">${v.phone||''}</span></td>
            <td style="font-size:0.82rem">${v.skills||'—'}</td>
            <td>📍 ${v.location||'—'}</td>
            <td><span class="badge ${v.availability==='available'?'badge-low':'badge-medium'}">${v.availability||'—'}</span></td>
            <td>${v.assigned_count||0}/${v.max_capacity||2} tasks</td>
          </tr>`).join("")}
      </tbody>
    </table>`;
}

// ─── MATCHES ──────────────────────────────────────────────────

async function loadMatches(useGemini) {
  const container = document.getElementById("matchesContainer");
  container.innerHTML = `<div class="loading-state">${spin()} ${useGemini ? "Gemini is scoring matches..." : "Running fast match..."}</div>`;

  const data = await apiFetch(`/matches?use_gemini=${useGemini}`);

  if (!data.matches || data.matches.length === 0) {
    container.innerHTML = `<div class="loading-state">No active needs to match. Submit a need first.</div>`;
    return;
  }

  container.innerHTML = data.matches.map(item => {
    const need = item.need;
    const matches = item.top_matches;
    const urgency = (need.urgency || "low").toLowerCase();

    return `
      <div class="need-card ${urgency}">
        <div class="need-header">
          <div>
            <div class="need-meta">
              ${badgeHTML(need.urgency)}
              <span class="badge" style="background:#e0f2fe;color:#0369a1">${need.category||'—'}</span>
            </div>
            <div class="need-desc">${need.description||''}</div>
            <div class="need-info">📍 ${need.location||'?'} · 👥 ${need.people_affected||'?'} people · 🏢 ${need.ngo_name||'NGO'}</div>
          </div>
          <div style="text-align:right">
            <div class="priority-chip">Score: ${need.priority_score||'—'}</div>
          </div>
        </div>
        <div class="volunteers-row">
          ${matches.length === 0
            ? '<div style="color:#64748b;font-size:0.86rem;padding:8px">No available volunteers found.</div>'
            : matches.map((v, i) => `
              <div class="vol-card ${i===0?'rank-1':''}">
                <div style="font-size:0.7rem;color:#7c3aed;font-weight:700">
                  ${["🥇 Best Match","🥈 2nd","🥉 3rd"][i]||`#${i+1}`}
                </div>
                <div class="vol-name">${v.name}</div>
                <div class="vol-score">${v.match_score}/100</div>
                <div class="vol-detail">
                  🛠 ${v.skills}<br>
                  📍 ${v.location}<br>
                  📏 ${v.distance_km >= 0 ? v.distance_km+'km away' : 'Distance N/A'}<br>
                  🎯 Skill fit: ${v.skill_relevance}/10
                </div>
                ${v.skill_reason ? `<div class="vol-reason">✨ ${v.skill_reason}</div>` : ''}
                <button class="btn-assign" onclick="confirmAssign('${need.id}','${v.volunteer_id}','${v.name}')">
                  ✅ Assign
                </button>
              </div>`).join("")}
        </div>
      </div>`;
  }).join("");
}

// ─── CONFIRM ASSIGNMENT ───────────────────────────────────────

async function confirmAssign(needId, volId, volName) {
  if (!confirm(`Assign ${volName} to this need?`)) return;

  const data = await apiFetch("/assign", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ need_id: needId, volunteer_id: volId })
  });

  if (data.success) {
    alert(`✅ ${volName} assigned successfully! Google Sheets updated.`);
    loadMatches(false);
    loadStats();
  } else {
    alert(`❌ Assignment failed: ${data.error}`);
  }
}

// ─── SUMMARY ──────────────────────────────────────────────────

async function loadSummary() {
  const box = document.getElementById("summaryBox");
  box.innerHTML = `${spin()} Gemini is analyzing the situation...`;
  const data = await apiFetch("/summary");
  box.innerHTML = data.summary
    ? `🧠 <strong>Coordinator Briefing</strong> (${data.needs_analyzed} needs analyzed):<br><br>${data.summary}`
    : "Could not generate summary. Add some needs first.";
}

// ─── BURNOUT ──────────────────────────────────────────────────

async function loadBurnout() {
  const container = document.getElementById("burnoutContainer");
  container.innerHTML = `<div class="loading-state">${spin()} Checking workloads...</div>`;
  const data = await apiFetch("/volunteers/burnout");
  const { overloaded=[], at_risk=[], safe_count=0, total=0 } = data;

  let html = `<div class="burnout-grid">
    <div class="burnout-alert safe">
      <div class="burnout-icon">📋</div>
      <div class="burnout-msg"><strong>Overview</strong>
        ${safe_count} healthy · ${at_risk.length} at risk · ${overloaded.length} overloaded · ${total} total
      </div>
    </div>`;

  overloaded.forEach(v => {
    html += `<div class="burnout-alert overloaded">
      <div class="burnout-icon">🚨</div>
      <div class="burnout-msg"><strong>OVERLOADED — ${v.name}</strong>${v.message}</div>
      <span class="badge badge-critical">${v.assigned_count} tasks</span>
    </div>`;
  });

  at_risk.forEach(v => {
    html += `<div class="burnout-alert at_risk">
      <div class="burnout-icon">⚠️</div>
      <div class="burnout-msg"><strong>AT RISK — ${v.name}</strong>${v.message}</div>
      <span class="badge badge-high">${v.assigned_count} tasks</span>
    </div>`;
  });

  if (!overloaded.length && !at_risk.length) {
    html += `<div class="burnout-alert safe">
      <div class="burnout-icon">✅</div>
      <div class="burnout-msg"><strong>All volunteers within healthy limits</strong></div>
    </div>`;
  }

  container.innerHTML = html + "</div>";
}

// ─── HEATMAP ──────────────────────────────────────────────────

async function loadHeatmap() {
  const container = document.getElementById("mapPoints");
  const legend = document.getElementById("mapLegend");
  container.innerHTML = `<div class="loading-state">${spin()} Loading map data...</div>`;

  const data = await apiFetch("/heatmap");

  if (!data.points || data.points.length === 0) {
    container.innerHTML = `<div class="loading-state">No geo-tagged needs found. Make sure needs have lat/lng coordinates.</div>`;
    return;
  }

  legend.classList.remove("hidden");

  const colorMap = { critical: "#dc2626", high: "#d97706", medium: "#7c3aed", low: "#16a34a" };

  container.innerHTML = data.points.map(p => `
    <div class="map-pin-card" style="border-left: 4px solid ${colorMap[p.urgency]||'#6b7280'}">
      <div class="map-pin-header">
        <span style="background:${colorMap[p.urgency]||'#6b7280'};color:white;padding:2px 8px;border-radius:12px;font-size:0.72rem;font-weight:700">
          ${p.urgency?.toUpperCase()}
        </span>
        <span style="font-size:0.75rem;color:#64748b">${p.category}</span>
        <span style="font-size:0.75rem;color:#2563eb;font-weight:700">Score: ${p.priority_score}</span>
      </div>
      <div style="font-size:0.88rem;margin:6px 0">${p.description}...</div>
      <div style="font-size:0.78rem;color:#64748b">
        📍 ${p.lat?.toFixed(4)}, ${p.lng?.toFixed(4)} &nbsp;·&nbsp;
        👥 ${p.people_affected} people &nbsp;·&nbsp;
        ${p.status}
      </div>
    </div>`).join("");
}

// ─── INSIGHTS ─────────────────────────────────────────────────

async function loadInsights() {
  const container = document.getElementById("insightsContainer");
  container.innerHTML = `<div class="loading-state">${spin()} Analyzing data patterns...</div>`;
  const data = await apiFetch("/insights");

  if (!data.insights) {
    container.innerHTML = `<div class="loading-state">No data yet. Submit and complete some needs first.</div>`;
    return;
  }

  container.innerHTML = `
    <div class="insights-grid">
      ${data.insights.map(ins => `
        <div class="insight-card">
          <div class="insight-icon">${ins.icon}</div>
          <div class="insight-title">${ins.title}</div>
          <div class="insight-value">${ins.value}</div>
          <div class="insight-detail">${ins.detail}</div>
        </div>`).join("")}
    </div>
    <p style="font-size:0.75rem;color:var(--muted);margin-top:12px">
      📊 ${data.data_points} data points · ${data.note}
    </p>`;
}
// ─── TASK COMPLETION ──────────────────────────────────────────

async function completeTask(needId, needDesc) {
  const outcome = confirm(
    `Mark this task as completed?\n\n"${needDesc}"\n\nClick OK for Successful, Cancel to abort.`
  ) ? "successful" : null;

  if (!outcome) return;

  const feedback = prompt("Optional feedback (press Enter to skip):") || "";

  const data = await apiFetch(`/needs/${needId}/complete`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ outcome, feedback })
  });

  if (data.success) {
    let msg = `✅ Task marked as completed!\n\nOutcome: ${data.outcome}`;

    if (data.reallocation) {
      const r = data.reallocation;
      msg += `\n\n🔄 SMART REALLOCATION:\n${r.message}`;
      if (confirm(msg + "\n\nAssign them to this new need?")) {
        // Auto-assign to suggested need
        const assignData = await apiFetch("/assign", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            need_id: r.suggested_need_id,
            volunteer_id: data.freed_volunteer_id
          })
        });
        if (assignData.success) {
          alert("✅ Volunteer reallocated to next priority need!");
        }
      }
    } else {
      alert(msg);
    }

    loadMatches(false);
    loadNeeds();
    loadStats();
    loadBurnout();
  } else {
    alert(`❌ Error: ${data.error}`);
  }
}


// ─── RESOURCE GAP ─────────────────────────────────────────────

async function loadResourceGap() {
  const container = document.getElementById("resourceGapContainer");
  container.innerHTML = `<div class="loading-state">${spin()} Analyzing resource gaps...</div>`;

  const data = await apiFetch("/resource-gap");

  if (!data.gaps) {
    container.innerHTML = `<div class="loading-state">No data available.</div>`;
    return;
  }

  const statusConfig = {
    critical_shortage: { color: "#dc2626", bg: "#fef2f2", label: "🚨 Critical Shortage", border: "#fca5a5" },
    shortage:          { color: "#d97706", bg: "#fffbeb", label: "⚠️ Shortage",          border: "#fcd34d" },
    balanced:          { color: "#16a34a", bg: "#f0fdf4", label: "✅ Balanced",           border: "#86efac" },
    surplus:           { color: "#2563eb", bg: "#eff6ff", label: "📦 Surplus",            border: "#bfdbfe" }
  };

  let html = `
    <div style="display:flex;gap:16px;margin-bottom:16px;font-size:0.85rem;flex-wrap:wrap">
      <span>📋 Active Needs: <strong>${data.total_active_needs}</strong></span>
      <span>👥 Available Volunteers: <strong>${data.total_available_volunteers}</strong></span>
    </div>
    <div class="gap-grid">`;

  data.gaps.forEach(g => {
    const cfg = statusConfig[g.status] || statusConfig.balanced;
    const barWidth = Math.min(100, (g.volunteers_available / Math.max(g.needs_count, 1)) * 100);

    html += `
      <div class="gap-card" style="border:1.5px solid ${cfg.border};background:${cfg.bg}">
        <div class="gap-header">
          <span class="gap-category">${g.category.replace("_"," ").toUpperCase()}</span>
          <span style="color:${cfg.color};font-size:0.78rem;font-weight:700">${cfg.label}</span>
        </div>
        <div class="gap-bars">
          <div class="gap-bar-row">
            <span class="gap-bar-label">Needs</span>
            <div class="gap-bar-track">
              <div class="gap-bar-fill" style="width:${Math.min(100,g.needs_count*20)}%;background:#dc2626"></div>
            </div>
            <span class="gap-bar-num">${g.needs_count}</span>
          </div>
          <div class="gap-bar-row">
            <span class="gap-bar-label">Volunteers</span>
            <div class="gap-bar-track">
              <div class="gap-bar-fill" style="width:${Math.min(100,g.volunteers_available*20)}%;background:#16a34a"></div>
            </div>
            <span class="gap-bar-num">${g.volunteers_available}</span>
          </div>
        </div>
        <div style="font-size:0.78rem;color:#64748b;margin-top:6px">
          Gap: <strong style="color:${cfg.color}">${g.gap > 0 ? '+'+g.gap+' more volunteers needed' : g.gap < 0 ? Math.abs(g.gap)+' surplus volunteers' : 'Perfectly balanced'}</strong>
        </div>
      </div>`;
  });

  html += `</div>`;
  container.innerHTML = html;
}


// ─── ENHANCED HEATMAP ────────────────────────────────────────

async function loadHeatmap(filter = 'both') {
  const container = document.getElementById("mapPoints");
  const legend = document.getElementById("heatmapLegend");
  container.innerHTML = `<div class="loading-state">${spin()} Loading map data...</div>`;

  const data = await apiFetch("/heatmap");

  if (!data.need_points && !data.volunteer_points) {
    container.innerHTML = `<div class="loading-state">No geo-tagged data found. Add lat/lng when submitting needs and registering volunteers.</div>`;
    return;
  }

  legend.classList.remove("hidden");
  const colorMap = { critical:"#dc2626", high:"#d97706", medium:"#7c3aed", low:"#16a34a" };

  let html = "";

  // Need pins
  if (filter === "both" || filter === "needs") {
    (data.need_points || []).forEach(p => {
      const color = colorMap[p.urgency] || "#6b7280";
      html += `
        <div class="map-pin-card" style="border-left:4px solid ${color}">
          <div class="map-pin-header">
            <span style="background:${color};color:white;padding:2px 8px;border-radius:12px;font-size:0.72rem;font-weight:700">
              📍 ${p.urgency?.toUpperCase()} NEED
            </span>
            <span style="font-size:0.75rem;color:#64748b">${p.category}</span>
            <span style="font-size:0.75rem;color:#2563eb;font-weight:700">Score:${p.priority_score}</span>
          </div>
          <div style="font-size:0.87rem;margin:6px 0;font-weight:500">${p.description}...</div>
          <div style="font-size:0.77rem;color:#64748b">
            🗺 ${p.lat?.toFixed(4)}, ${p.lng?.toFixed(4)} · 
            👥 ${p.people_affected} people · 
            🏢 ${p.ngo_name||'NGO'} ·
            <span style="color:${p.status==='assigned'?'#16a34a':'#d97706'}">${p.status}</span>
          </div>
        </div>`;
    });
  }

  // Volunteer pins
  if (filter === "both" || filter === "volunteers") {
    (data.volunteer_points || []).forEach(v => {
      const isAvailable = v.availability === "available";
      html += `
        <div class="map-pin-card" style="border-left:4px solid ${isAvailable ? '#2563eb' : '#9ca3af'}">
          <div class="map-pin-header">
            <span style="background:${isAvailable?'#2563eb':'#9ca3af'};color:white;padding:2px 8px;border-radius:12px;font-size:0.72rem;font-weight:700">
              👤 VOLUNTEER
            </span>
            <span style="font-size:0.75rem;color:${isAvailable?'#16a34a':'#dc2626'};font-weight:600">
              ${isAvailable ? '✅ Available' : '⏸ Busy'}
            </span>
          </div>
          <div style="font-size:0.87rem;margin:6px 0;font-weight:500">${v.name}</div>
          <div style="font-size:0.77rem;color:#64748b">
            🛠 ${v.skills} · 
            🗺 ${v.lat?.toFixed(4)}, ${v.lng?.toFixed(4)} · 
            📋 ${v.assigned_count} tasks active
          </div>
        </div>`;
    });
  }

  if (!html) {
    container.innerHTML = `<div class="loading-state">No data for this filter. Try "Show Both".</div>`;
    return;
  }

  container.innerHTML = html;
}


// ─── UPDATE loadMatches TO SHOW COMPLETE BUTTON ───────────────

async function loadMatches(useGemini) {
  const container = document.getElementById("matchesContainer");
  container.innerHTML = `<div class="loading-state">${spin()} ${useGemini?"Gemini scoring...":"Fast matching..."}</div>`;

  const data = await apiFetch(`/matches?use_gemini=${useGemini}`);

  if (!data.matches || data.matches.length === 0) {
    container.innerHTML = `<div class="loading-state">No active needs. Submit a need first.</div>`;
    return;
  }

  container.innerHTML = data.matches.map(item => {
    const need = item.need;
    const matches = item.top_matches;
    const urgency = (need.urgency || "low").toLowerCase();
    const isAssigned = need.status === "assigned";

    return `
      <div class="need-card ${urgency}">
        <div class="need-header">
          <div>
            <div class="need-meta">
              ${badgeHTML(need.urgency)}
              <span class="badge" style="background:#e0f2fe;color:#0369a1">${need.category||'—'}</span>
              <span class="badge" style="background:${isAssigned?'#f0fdf4':'#f1f5f9'};color:${isAssigned?'#16a34a':'#64748b'}">
                ${need.status||'pending'}
              </span>
            </div>
            <div class="need-desc">${need.description||''}</div>
            <div class="need-info">
              📍 ${need.location||'?'} · 👥 ${need.people_affected||'?'} people · 
              🏢 ${need.ngo_name||'NGO'} · 🆔 ${need.id}
            </div>
          </div>
          <div style="display:flex;flex-direction:column;gap:6px;align-items:flex-end">
            <div class="priority-chip">Score: ${need.priority_score||'—'}</div>
            ${isAssigned ? `
              <button class="btn-complete" onclick="completeTask('${need.id}','${(need.description||'').substring(0,50)}')">
                ✅ Mark Complete
              </button>` : ''}
          </div>
        </div>
        <div class="volunteers-row">
          ${matches.length === 0
            ? '<div style="color:#64748b;font-size:0.86rem;padding:8px">No available volunteers.</div>'
            : matches.map((v, i) => `
              <div class="vol-card ${i===0?'rank-1':''}">
                <div style="font-size:0.7rem;color:#7c3aed;font-weight:700">
                  ${["🥇 Best Match","🥈 2nd","🥉 3rd"][i]||"#"+(i+1)}
                </div>
                <div class="vol-name">${v.name}</div>
                <div class="vol-score">${v.match_score}/100</div>
                <div class="vol-detail">
                  🛠 ${v.skills}<br>
                  📍 ${v.location}<br>
                  📏 ${v.distance_km>=0?v.distance_km+'km':'N/A'}<br>
                  🎯 Skill fit: ${v.skill_relevance}/10
                </div>
                ${v.skill_reason?`<div class="vol-reason">✨ ${v.skill_reason}</div>`:''}
                ${!isAssigned ? `
                  <button class="btn-assign"
                    onclick="confirmAssign('${need.id}','${v.volunteer_id}','${v.name}')">
                    📋 Assign
                  </button>` : ''}
              </div>`).join("")}
        </div>
      </div>`;
  }).join("");
}
// ─── INIT ─────────────────────────────────────────────────────
loadStats();
loadSummary();
loadNeeds();
loadBurnout();
