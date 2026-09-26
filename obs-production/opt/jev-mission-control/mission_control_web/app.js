"use strict";

let current = null;
let fetching = false;
let failed = false;
const byId = (id) => document.getElementById(id);
const text = (id, value) => { byId(id).textContent = value; };
const human = (value) => String(value || "").replaceAll("_", " ").replaceAll("-", " ");
const title = (value) => human(value).replace(/\b\w/g, (character) => character.toUpperCase());
const numeric = (value) => typeof value === "number" && Number.isFinite(value);
const format = (value) => numeric(value) ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 }).format(value) : "—";
const time = (value) => numeric(value) ? new Date(value * 1000).toLocaleTimeString("en-GB", { timeZone: "UTC", hour12: false }) + " UTC" : "—";
const node = (tag, className, value) => {
  const element = document.createElement(tag);
  if (className) element.className = className;
  if (value !== undefined) element.textContent = value;
  return element;
};
const items = (value) => Object.entries(value || {}).map(([name, count]) => `${format(count)} ${human(name)}`).join(" · ");

function clocks() {
  text("clock", time(Date.now() / 1000));
  if (!current) return;
  const now = Date.now() / 1000;
  const age = numeric(current.generated_at) ? now - current.generated_at : Infinity;
  const gameAge = numeric(current.telemetry_at) ? Math.max(0, now - current.telemetry_at) : Infinity;
  const stale = age > 20 || age < -30 || failed;
  const delayed = gameAge > 90;
  const active = current.phase === "gameplay" && current.process_alive;
  const badge = byId("connection");
  badge.className = `badge ${stale ? "bad" : active ? "good" : "warn"}`;
  badge.textContent = stale ? "FEED STALE" : active ? "CONNECTED" : "OBSERVER ONLINE";
  const messages = [];
  if (stale) messages.push("Telemetry delivery is stale or disconnected. Displaying the last received snapshot—not confirmed live state.");
  else if (current.repair_required) messages.push(`Gameplay is paused for repair attempt ${current.repair_attempt}. A running repair process is not gameplay progress.`);
  else if (current.status === "unavailable") messages.push("Campaign evidence is missing or session identities do not match.");
  else if (["blocked", "uncertain", "stopped", "cutoff"].includes(current.status)) messages.push(`Controller is ${current.status}. No active gameplay progress is claimed.`);
  if (delayed && !stale) messages.push("The game observation is older than 90 seconds. A long-running action may be in progress; values below are historical.");
  byId("notice").hidden = messages.length === 0;
  text("notice", messages.join(" "));
  text("status", stale ? "Unknown / stale" : title(current.status));
  text("telemetry-age", Number.isFinite(gameAge) ? `Observed ${Math.floor(gameAge)}s ago` : "No game observation");
  if (numeric(current.cutoff)) {
    const remaining = Math.max(0, Math.floor(current.cutoff - now));
    const hours = Math.floor(remaining / 3600);
    const minutes = Math.floor(remaining % 3600 / 60);
    const seconds = remaining % 60;
    text("remaining", [hours, minutes, seconds].map((value) => String(value).padStart(2, "0")).join(":"));
    text("deadline", `Original cutoff · ${time(current.cutoff)}`);
    const duration = current.cutoff - current.started_at;
    byId("elapsed-bar").style.width = `${numeric(current.started_at) && duration > 0 ? Math.max(0, Math.min(100, (now - current.started_at) / duration * 100)) : 0}%`;
  }
}

function render(data) {
  current = data;
  text("session", `SESSION ${data.session_id ? data.session_id.slice(0, 12) : "UNKNOWN"}`);
  text("policy", `${String(data.model.policy || "unknown").toUpperCase()} POLICY`);
  text("started", `START ${time(data.started_at)}`);
  text("phase", `${title(data.phase)} · ${data.process_alive ? "owned process alive" : "no live owned process"}`);
  text("tick", format(data.tick));
  const progress = numeric(data.research.progress) ? Math.max(0, Math.min(1, data.research.progress)) : null;
  const percent = progress === null ? "—" : `${(progress * 100).toFixed(1)}%`;
  text("research-percent", percent);
  text("research-name", title(data.research.name) || "No current research");
  text("research-title", title(data.research.name) || "No current research");
  text("research-ratio", percent);
  text("research-completed", `${data.research.completed.length} technologies observed complete`);
  byId("research-bar").style.width = `${(progress || 0) * 100}%`;
  const goals = [["stockpile_fuel", "01 Fuel"], ["bootstrap_mining", "02 Mining"], ["rocket_launch", "03 Launch"]];
  text("milestone-count", `${goals.filter(([key]) => Object.hasOwn(data.completed_goals, key)).length} / 3`);
  byId("milestones").replaceChildren(...goals.map(([key, name]) => node("div",
    `milestone ${Object.hasOwn(data.completed_goals, key) ? "done" : data.active_goal === key ? "active" : ""}`, name)));
  text("operation", data.plan.description || (data.repair_required ? "Repair gate active" : "Observing & selecting next plan"));
  text("operation-detail", data.plan.pending_action ? `${title(data.plan.pending_action)} · ${data.plan.dispatch || "pending"} dispatch. Awaiting observed evidence, not assuming success.` : "The controller selects and verifies actions. This dashboard has no mutation endpoints.");
  text("dispatch", data.plan.dispatch ? data.plan.dispatch.toUpperCase() : "OBSERVING");
  text("goal", `GOAL ${human(data.active_goal || data.target).toUpperCase()}`);
  text("polls", `OBSERVATIONS ${data.plan.polls}`);
  text("machine-count", `${data.machines.length} machines`);
  byId("machine-empty").hidden = data.machines.length > 0;
  byId("machines").replaceChildren(...data.machines.map((machine) => {
    const row = node("tr");
    const identity = node("td");
    identity.append(node("strong", "", title(machine.name)), node("small", "", human(machine.role)));
    const status = node("td");
    status.append(node("span", `badge ${machine.crafting ? "good" : "neutral"}`, machine.crafting ? "CRAFTING" : `STATUS ${machine.status_code ?? "?"}`));
    const input = node("td", "", items(machine.input) || "—");
    if (Object.keys(machine.fuel).length) input.append(node("small", "", `Fuel: ${items(machine.fuel)}`));
    row.append(identity, status, input, node("td", "", items(machine.output) || "—"));
    return row;
  }));
  const inventory = Object.entries(data.inventory).filter(([, count]) => count > 0).sort((left, right) => right[1] - left[1]);
  text("inventory-count", `${inventory.length} ITEM TYPES`);
  const maximum = Math.max(1, ...inventory.map(([, count]) => count));
  byId("inventory").replaceChildren(...inventory.slice(0, 10).map(([name, count]) => {
    const row = node("div", "inventory-row");
    const line = node("div", "inventory-line");
    line.append(node("span", "", title(name)), node("strong", "", format(count)));
    const track = node("div", "inventory-track");
    const bar = node("div");
    bar.style.width = `${count / maximum * 100}%`;
    track.append(bar);
    row.append(line, track);
    return row;
  }));
  if (!inventory.length) byId("inventory").append(node("p", "muted", "No items in the last observed inventory."));
  byId("events").replaceChildren(...data.events.slice(-12).reverse().map((event) => {
    const row = node("div", "event");
    const detail = node("div");
    detail.append(node("div", "event-title", title(event.kind)), node("div", "event-detail", human(event.action || event.plan)));
    row.append(node("span", `event-mark ${event.kind === "step_verified" ? "verified" : ""}`), detail, node("span", "event-tick", `t ${format(event.tick)}`));
    return row;
  }));
  if (!data.events.length) byId("events").append(node("p", "muted", "No controller events received."));
  text("repair-attempt", `ATTEMPT ${data.repair_attempt}`);
  text("repair-state", data.repair_required ? "Repair required. Gameplay is gated until the supervisor accepts evidence." : "No active repair gate. Historical failures remain preserved.");
  text("failure-count", `${format(data.retained_failures)} HISTORICAL FAILURES RETAINED`);
  byId("repairs").replaceChildren(...data.repairs.slice(0, 6).map((repair) => {
    const row = node("div", "repair-row");
    const detail = node("div");
    detail.append(node("div", "repair-title", title(repair.event)), node("div", "repair-date", `${time(repair.at)}${repair.attempt ? ` · attempt ${repair.attempt}` : ""}`));
    const verdict = repair.accepted === true ? "ACCEPTED" : repair.accepted === false ? "NOT ACCEPTED" : "RECORDED";
    row.append(detail, node("span", `badge ${repair.accepted === true ? "good" : repair.accepted === false ? "warn" : "neutral"}`, verdict));
    return row;
  }));
  text("updated", `SNAPSHOT ${time(data.generated_at)}`);
  clocks();
}

async function refresh() {
  if (fetching) return;
  fetching = true;
  try {
    const response = await fetch("/api/status", { cache: "no-store", signal: AbortSignal.timeout(4000) });
    if (!response.ok) throw new Error("No telemetry");
    const data = await response.json();
    if (data.schema_version !== 1) throw new Error("Unsupported telemetry");
    failed = false;
    render(data);
  } catch {
    failed = true;
    if (!current) {
      text("connection", "NO TELEMETRY");
      byId("connection").className = "badge bad";
      text("notice", "Waiting for the read-only telemetry exporter. No live status is available.");
    }
    clocks();
  } finally {
    fetching = false;
  }
}

byId("refresh").addEventListener("click", refresh);
document.querySelectorAll("nav a").forEach((link) => link.addEventListener("click", () => {
  document.querySelectorAll("nav a").forEach((item) => item.classList.toggle("selected", item === link));
}));
setInterval(refresh, 5000);
setInterval(clocks, 1000);
refresh();
