/* پنل مدیریت Legal-Automation — SPA ساده بدون وابستگی (متمایز از طرح مرجع React/Next) */
"use strict";

const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));
const API = "/api";
let page = { users: 1, invoices: 1, runs: 1, errors: 1, notices: 1, cases: 1, support: 1 };
let curSec = "dashboard";

/* ── کمکی ── */
function fa(n) { return (n ?? 0).toLocaleString("fa-IR"); }
function esc(s) { return String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
async function api(path, opts = {}) {
  opts.headers = Object.assign({ "X-Panel-CSRF": "1" }, opts.headers || {});
  if (opts.body && typeof opts.body === "object") {
    opts.headers["Content-Type"] = "application/json";
    opts.body = JSON.stringify(opts.body);
  }
  const r = await fetch(API + path, opts);
  if (r.status === 401) { showLogin(); throw new Error("نشست منقضی شد"); }
  const j = await r.json().catch(() => ({}));
  if (!r.ok) { toast(j.detail || "خطا", "bad"); throw new Error(j.detail || "http " + r.status); }
  return j;
}
function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = "toast " + kind; t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), 4200);
}
function tag(text, cls) { return `<span class="tag ${esc(cls || "")}">${esc(text)}</span>`; }

const PLAN_FA = { free: "رایگان", base: "پایه", select: "برگزیده", pro: "پیشرو", expert: "تخصصی", org: "سازمانی", "-": "بدون پلن" };
const STATUS_FA = { NEW: ["جدید", "info"], FREE_ACTIVE: ["فعال رایگان", "ok"], PAID_ACTIVE: ["پرداختی", "ok"], LOCKED: ["قفل", "bad"] };
const INV_STATUS_FA = { pending: ["در انتظار پرداخت", "warn"], receipt_sent: ["رسید ارسال‌شده", "info"], shortfall_wait: ["در انتظار کسری", "warn"], approved: ["تأییدشده", "ok"], rejected: ["ردشده", "bad"], expired: ["منقضی", "bad"], used: ["مصرف‌شده", "info"] };
const KIND_FA = { new: "خرید", upgrade: "ارتقا", renewal: "تمدید", turn: "نوبت قضائی" };
const EV_FA = { free_start: "شروع رایگان", plan_activated: "فعال‌سازی پلن", plan_upgraded: "ارتقا", inquiry_used: "مصرف استعلام", quota_reset: "ریست سهمیه", restricted: "محدودیت", violation_reported: "گزارش تخلف", renewed: "تمدید", degraded: "تخفیف پلن", locked: "قفل", unrestricted: "برداشتن محدودیت" };
const RUN_KIND_FA = { notices_new: "ابلاغیه جدید", notices_case: "ابلاغیه پرونده", notices_range: "بازه", case_list: "فهرست پرونده", case_detail: "جزئیات پرونده", case_track: "پیگیری", turn: "نوبت" };

/* ── ورود/خروج ── */
function showLogin() { $("#appView").classList.add("hidden"); $("#loginView").classList.remove("hidden"); }
async function tryResume() {
  try { await api("/stats"); $("#loginView").classList.add("hidden"); $("#appView").classList.remove("hidden"); go(location.hash || "#dashboard"); }
  catch { showLogin(); }
}
$("#loginForm").addEventListener("submit", async (e) => {
  e.preventDefault();
  try {
    await api("/login", { method: "POST", body: { password: $("#loginPass").value } });
    $("#loginErr").textContent = ""; $("#loginPass").value = "";
    $("#loginView").classList.add("hidden"); $("#appView").classList.remove("hidden");
    go(location.hash || "#dashboard"); toast("خوش آمدید 👋");
  } catch (err) { $("#loginErr").textContent = err.message || "رمز اشتباه است."; }
});
$("#logoutBtn").addEventListener("click", async () => { try { await api("/logout", { method: "POST" }); } catch {} showLogin(); });

/* ── ساعت تهران ── */
setInterval(() => {
  $("#clock").textContent = new Intl.DateTimeFormat("fa-IR-u-nu-latn", {
    timeZone: "Asia/Tehran", weekday: "long", hour: "2-digit", minute: "2-digit", second: "2-digit"
  }).format(new Date());
}, 1000);

/* ── ناوبری ── */
const SECS = {
  dashboard: ["داشبورد", "نمای کلی ربات در یک نگاه"], users: ["کاربران", "جستجو، پلن و محدودسازی"],
  invoices: ["فاکتورها", "تأیید / رد / کسری رسید کارت‌به‌کارت"], runs: ["بررسی‌ها", "لاگ اجرای استعلام‌ها"],
  errors: ["خطاها", "رویدادهای خطای ربات"], notices: ["ابلاغیه‌ها", "آخرین ابلاغیه‌های ثبت‌شده"],
  cases: ["پرونده‌های پیگیری", "پیگیری خودکار تغییرات"], support: ["پشتیبانی", "گفتگوی کاربر ↔ مدیر (پیش‌نویس + تایید)"],
  broadcast: ["پیام همگانی", "ارسال از طریق بله"],
  beta: ["فهرست بتا", "دسترسی تست پیش از انتشار"], settings: ["تنظیمات", "پارامترهای فعال ربات"],
};
function go(hash) {
  const sec = (hash || "#dashboard").replace("#", "");
  if (!SECS[sec]) return go("#dashboard");
  curSec = sec;
  location.hash = "#" + sec;
  $$("#nav a").forEach(a => a.classList.toggle("on", a.dataset.sec === sec));
  $$(".sec").forEach(s => s.classList.add("hidden"));
  $("#sec-" + sec).classList.remove("hidden");
  $("#secTitle").textContent = SECS[sec][0];
  $("#secSub").textContent = SECS[sec][1];
  load(sec);
}
window.addEventListener("hashchange", () => go(location.hash));
$("#nav").addEventListener("click", (e) => {
  const a = e.target.closest("a"); if (!a) return;
  e.preventDefault(); go(a.getAttribute("href"));
});
$("#refreshBtn").addEventListener("click", () => { load(curSec); toast("بازخوانی شد"); });

/* ── بارگذاری بخش‌ها ── */
async function load(sec) {
  try {
    if (sec === "dashboard") await loadDashboard();
    else if (sec === "users") await loadUsers();
    else if (sec === "invoices") await loadInvoices();
    else if (sec === "runs") await loadRuns();
    else if (sec === "errors") await loadErrors();
    else if (sec === "notices") await loadNotices();
    else if (sec === "cases") await loadCases();
    else if (sec === "support") await loadSupport();
    else if (sec === "broadcast") loadSys();
    else if (sec === "beta") await loadBeta();
    else if (sec === "settings") await loadSettings();
  } catch (e) { /* toast در api زده شد */ }
}

/* ── داشبورد ── */
async function loadDashboard() {
  const s = await api("/stats");
  const k = s.kpis;
  $("#kpiGrid").innerHTML = [
    ["کاربران", fa(k.users), ""], ["مشترک فعال", fa(k.active), "acc"],
    ["فاکتور در انتظار", fa(k.pending_inv), k.pending_inv ? "warn" : ""],
    ["تأیید ۷ روزه", fa(k.approved_inv), ""], ["درآمد ۷ روزه", fa(k.revenue_toman) + " ت", "acc"],
    ["بررسی ۲۴س", fa(k.runs24), ""], ["خطای ۲۴س", fa(k.errors24), k.errors24 ? "bad" : ""],
    ["محدودشده", fa(k.restricted), k.restricted ? "bad" : ""],
  ].map(([t, v, c]) => `<div class="kpi ${c}"><small>${t}</small><b>${v}</b></div>`).join("");

  const mx = Math.max(1, ...s.chart.map(c => c.ok + c.bad));
  $("#chartRuns").innerHTML = s.chart.map(c => `
    <div class="bar-col">
      <div class="bar-stack">
        <div class="bar bad" style="height:${c.bad / mx * 100}px" title="ناموفق: ${c.bad}"></div>
        <div class="bar ok" style="height:${c.ok / mx * 100}px" title="موفق: ${c.ok}"></div>
      </div>
      <div class="bar-val">${fa(c.ok + c.bad)}</div>
      <div class="bar-lbl">${c.day}<br>${c.wd}</div>
    </div>`).join("");

  const tot = Math.max(1, s.plans.reduce((a, p) => a + p.c, 0));
  $("#chartPlans").innerHTML = s.plans.map(p => `
    <div class="pl"><span>${esc(PLAN_FA[p.plan] || p.plan)}</span>
      <span class="track"><i style="width:${p.c / tot * 100}%"></i></span>
      <b>${fa(p.c)}</b></div>`).join("") || `<p class="empty">مشترکی نیست.</p>`;

  $("#eventsFeed").innerHTML = s.events.map(e => `
    <div class="fe"><span class="when">${esc(e.created_at_fa || "-")}</span>
      <span class="who">${esc(e.first_name || e.bale_id)}</span>
      <span class="what ev-${esc(e.event)}"><b>${esc(EV_FA[e.event] || e.event)}</b> ${esc(e.detail || "")}</span></div>`)
    .join("") || `<p class="empty">رویدادی نیست.</p>`;
  await updateBadge();
}

async function updateBadge() {
  try {
    const inv = await api(`/invoices?page=1`);
    const wait = inv.rows.filter(r => ["receipt_sent", "shortfall_wait"].includes(r.status)).length;
    const b = $("#invBadge");
    if (wait) { b.textContent = fa(wait); b.classList.remove("hidden"); }
    else b.classList.add("hidden");
  } catch {}
}

/* ── کاربران ── */
async function loadUsers() {
  const q = $("#userSearch").value.trim(), plan = $("#userPlan").value, st = $("#userStatus").value;
  const d = await api(`/users?page=${page.users}&q=${encodeURIComponent(q)}&plan=${encodeURIComponent(plan)}&status=${encodeURIComponent(st)}`);
  const body = $("#usersTable tbody");
  body.innerHTML = d.rows.map(u => {
    const quota = u.quota_total > 0 ? `${fa(u.quota_used)}/${fa(u.quota_total)}` : (u.quota_used ? fa(u.quota_used) : "—");
    const [stt, stc] = STATUS_FA[u.status] || [u.status, ""];
    return `<tr>
      <td class="num">${u.bale_id}</td>
      <td>${esc(u.first_name || "—")}</td>
      <td>${tag(stt, stc)}</td>
      <td>${u.plan ? tag(PLAN_FA[u.plan] || u.plan, u.plan === "free" ? "" : "info") : '<span class="tag">—</span>'}</td>
      <td class="num">${u.inquiries_left != null ? "اعتبار: " + fa(u.inquiries_left) : ""}${u.quota_total ? (u.inquiries_left != null ? " · " : "") + "سهمیه: " + quota : ""}</td>
      <td class="num">${esc(u.phone || "—")}</td>
      <td>${u.restricted_until ? tag("محدود تا " + (u.restricted_until_fa || ""), "bad") : "—"}</td>
      <td class="num">${u.created_at_fa || "—"}</td>
      <td class="actions"><button class="btn" data-act="user" data-id="${u.bale_id}">جزئیات</button></td>
    </tr>`;
  }).join("") || `<tr><td colspan="9" class="empty">کاربری یافت نشد.</td></tr>`;
  pagerInfo("usersPageInfo", d.total, page.users, 25);
}

/* ── فاکتورها ── */
async function loadInvoices() {
  const st = $("#invStatus").value === "all" ? "" : $("#invStatus").value;
  const q = $("#invSearch").value.trim();
  const d = await api(`/invoices?page=${page.invoices}&status=${encodeURIComponent(st)}&q=${encodeURIComponent(q)}`);
  $("#invTable tbody").innerHTML = d.rows.map(i => {
    const [stt, stc] = INV_STATUS_FA[i.status] || [i.status, ""];
    const actionable = ["receipt_sent", "pending", "shortfall_wait"].includes(i.status);
    return `<tr>
      <td class="num">${esc(i.code)}</td>
      <td>${esc(i.first_name || "")} <span class="num">(${i.bale_id})</span></td>
      <td>${esc(KIND_FA[i.kind] || i.kind)}</td>
      <td class="num">${fa(i.amount_toman)}${i.wallet_used ? "<br><small>(+ کیف پول " + fa(i.wallet_used) + ")</small>" : ""}</td>
      <td>${i.plan ? tag(PLAN_FA[i.plan] || i.plan, "info") + " " + (i.cycle === "quarterly" ? "(۳ ماهه)" : "") : "—"}</td>
      <td>${tag(stt, stc)}${i.shortfall_toman ? "<br><small>کسری: " + fa(i.shortfall_toman) + "</small>" : ""}${i.wallet_used ? "<br><small>کیف پول: " + fa(i.wallet_used) + "</small>" : ""}</td>
      <td class="num">${i.created_at_fa || "—"}</td>
      <td class="num">${i.expires_at_fa || "—"}</td>
      <td class="actions">${actionable ? `
        <button class="btn" data-act="inv-ok" data-code="${esc(i.code)}">تأیید</button>
        <button class="btn btn-danger" data-act="inv-no" data-code="${esc(i.code)}">رد</button>
        ${i.status === "receipt_sent" ? `<button class="btn" data-act="inv-short" data-code="${esc(i.code)}" data-amt="${i.amount_toman || 0}">کسری</button>` : ""}` : `<button class="btn" data-act="user" data-id="${i.bale_id}">کاربر</button>`}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="9" class="empty">فاکتوری در این وضعیت نیست.</td></tr>`;
  pagerInfo("invPageInfo", d.total, page.invoices, 25);
  await updateBadge();
}

/* ── گزارش‌ها ── */
async function loadRuns() {
  const st = $("#runStatus").value, q = $("#runUser").value.trim();
  const d = await api(`/runs?page=${page.runs}&status=${encodeURIComponent(st)}&q=${encodeURIComponent(q)}`);
  $("#runsTable tbody").innerHTML = d.rows.map(r => {
    const cls = r.status === "done" ? "ok" : (r.status === "running" ? "info" : "bad");
    return `<tr>
      <td class="num">${r.id}</td>
      <td>${esc(r.first_name || "")} <span class="num">(${r.bale_id || "—"})</span></td>
      <td>${esc(RUN_KIND_FA[r.kind] || r.kind)}</td>
      <td>${r.trigger === "manual" ? "دستی" : "زمان‌بندی"}</td>
      <td>${tag(r.status, cls)}</td>
      <td>${esc(r.step || "—")}</td>
      <td class="num">${fa(r.new_items || 0)}</td>
      <td>${r.error_code ? tag(r.error_code, "bad") : "—"}</td>
      <td class="num">${r.started_at || "—"}</td>
      <td class="num">${r.finished_at || "—"}</td></tr>`;
  }).join("") || `<tr><td colspan="10" class="empty">بررسی‌ای ثبت نشده.</td></tr>`;
  pagerInfo("runsPageInfo", d.total, page.runs, 30);
}
async function loadErrors() {
  const d = await api(`/errors?page=${page.errors}`);
  $("#errTable tbody").innerHTML = d.rows.map(e => `<tr>
    <td class="num">${e.id}</td>
    <td>${esc(e.first_name || "")} <span class="num">(${e.bale_id || "—"})</span></td>
    <td class="num">${esc(e.run_id || "—")}</td><td>${esc(e.step || "—")}</td>
    <td>${tag(e.category, "bad")}</td>
    <td style="white-space:normal;min-width:260px">${esc((e.message || "").slice(0, 160))}</td>
    <td class="num">${e.created_at || "—"}</td></tr>`).join("") || `<tr><td colspan="7" class="empty">خطایی ثبت نشده. 👍</td></tr>`;
  pagerInfo("errPageInfo", d.total, page.errors, 30);
}
async function loadNotices() {
  const q = $("#noticeSearch").value.trim();
  const d = await api(`/notices?page=${page.notices}&q=${encodeURIComponent(q)}`);
  $("#noticeTable tbody").innerHTML = d.rows.map(n => `<tr>
    <td>${esc(n.first_name || "")} <span class="num">(${n.bale_id})</span></td>
    <td class="num">${esc(n.external_id || "—")}</td>
    <td class="num">${esc(n.case_number || "—")}</td>
    <td>${esc(n.branch || "—")}</td><td>${esc(n.notice_type || "—")}</td>
    <td class="num">${n.sent_date_fa || "—"}</td>
    <td>${tag(n.status === "done" ? "دیده‌شده" : "باز", n.status === "done" ? "info" : "warn")}</td></tr>`)
    .join("") || `<tr><td colspan="7" class="empty">ابلاغیه‌ای نیست.</td></tr>`;
  pagerInfo("noticePageInfo", d.total, page.notices, 30);
}
async function loadCases() {
  const d = await api(`/cases?page=${page.cases}`);
  $("#caseTable tbody").innerHTML = d.rows.map(c => `<tr>
    <td>${esc(c.first_name || "")} <span class="num">(${c.bale_id})</span></td>
    <td class="num">${esc(c.case_number)}</td>
    <td>${c.portal === "lawyer" ? "وکیل" : "شخص"}</td>
    <td class="num">${c.last_change_fa || "—"}</td>
    <td class="num">${c.last_checked_fa || "—"}</td></tr>`).join("") || `<tr><td colspan="5" class="empty">پرونده‌ای پیگیری نمی‌شود.</td></tr>`;
  pagerInfo("casePageInfo", d.total, page.cases, 30);
}

/* ── پشتیبانی ── */
async function loadSupport() {
  const q = $("#supSearch").value.trim();
  const d = await api(`/support?page=${page.support}&q=${encodeURIComponent(q)}`);
  $("#supTable tbody").innerHTML = d.rows.map(m => `<tr>
    <td class="num">${m.id}</td>
    <td>${esc(m.first_name || "")} <span class="num">(${m.bale_id})</span></td>
    <td>${m.sender === "admin" ? tag("مدیر", "info") : tag("کاربر", "")}</td>
    <td style="white-space:normal;min-width:280px">${esc((m.body || "(بدون متن)").slice(0, 220))}</td>
    <td class="num">${m.files_count ? "📎 " + fa(m.files_count) : "—"}</td>
    <td class="num">${m.created_at_fa || "—"}</td>
    <td class="actions"><button class="btn" data-act="user" data-id="${m.bale_id}">کاربر</button></td></tr>`)
    .join("") || `<tr><td colspan="7" class="empty">پیام پشتیبانی‌ای ثبت نشده.</td></tr>`;
  pagerInfo("supPageInfo", d.total, page.support, 30);
}

/* ── بتا ── */
async function loadBeta() {
  const d = await api("/beta");
  $("#betaTable tbody").innerHTML = d.rows.map(b => `<tr>
    <td class="num">${b.bale_id}</td><td>${esc(b.first_name || "—")}</td>
    <td class="num">${b.created_at_fa || "—"}</td>
    <td class="actions"><button class="btn btn-danger" data-act="del-beta" data-id="${b.bale_id}">حذف</button></td></tr>`)
    .join("") || `<tr><td colspan="4" class="empty">فهرست بتا خالی است.</td></tr>`;
}

/* ── تنظیمات ── */
async function loadSettings() {
  const s = await api("/settings");
  const row = (k, v) => `<div class="row"><span>${k}</span><span>${v ?? "—"}</span></div>`;
  $("#settingsBody").innerHTML = `
    <div class="card settings-cards"><h3>💳 پرداخت کارت‌به‌کارت</h3>
      ${row("شماره کارت", esc(s.card.number))}${row("دارنده", esc(s.card.holder))}
      ${row("بانک", esc(s.card.bank))}${row("برند", esc(s.card.brand))}</div>
    <div class="card settings-cards"><h3>🏷 قیمت‌ها (تومان)</h3>
      ${row("نوبت قضائی", s.prices.turn)}${row("پایه", s.prices.base)}${row("برگزیده", s.prices.select)}
      ${row("پیشرو ماهانه", s.prices.pro_m)}${row("پیشرو ۳ ماهه", s.prices.pro_q)}
      ${row("تخصصی ماهانه", s.prices.expert_m)}${row("تخصصی ۳ ماهه", s.prices.expert_q)}
      ${row("سازمانی ماهانه", s.prices.org_m)}${row("سازمانی ۳ ماهه", s.prices.org_q)}</div>
    <div class="card settings-cards"><h3>🚦 محدودیت‌ها</h3>
      ${row("استعلام شروع رایگان", fa(s.limits.free_inquiries))}
      ${row("انقضای فاکتور (ساعت)", fa(s.limits.expire_hours))}
      ${row("سقف مصرف عادی در ساعت", fa(s.limits.abuse_per_hour))}
      ${row("مدت محدودیت (ساعت)", fa(s.limits.restrict_hours))}
      ${row("سقف روزانه سازمانی", fa(s.limits.org_daily_cap))}
      ${row("مهلت پرونده بعد از انقضا (روز)", fa(s.limits.grace_days))}
      ${row("مرورگر هم‌زمان / کمینه رم آزاد", fa(s.limits.max_concurrent_browsers) + " / " + fa(s.limits.min_free_ram) + "MB")}</div>
    <div class="card settings-cards"><h3>⏰ زمان‌بندی و پشتیبانی</h3>
      ${row("ساعت‌های بررسی", esc(s.times.checks))}${row("پیگیری پرونده", esc(s.times.case_track))}
      ${row("یادآوری", esc(s.times.reminder))}${row("تلفن پشتیبانی", esc(s.support.phone))}
      ${row("ربات لاویه", esc(s.support.lavayeh_bot))}
      ${row("حساب مدیر رایگان", s.admin_free ? "فعال" : "خاموش")}
      ${row("نسخه راهنما", fa(s.guide_version) + (s.guide_file_set ? " (PDF ثبت شده)" : " (بدون فایل)"))}
      ${row("پورت پنل", fa(s.panel_port))}</div>`;
}

/* ── سیستم (سایدبار + broadcast) ── */
async function loadSys() {
  try {
    const s = await api("/system");
    const ok = s.bot.ok;
    $("#sysPill").innerHTML = `وضعیت: ${ok ? '<b class="ok">ربات متصل ✔</b>' : '<b class="no">ربات جدا ✖</b>'} · دیتابیس ${esc(s.db_path)}` +
      (s.ram ? ` · رم آزاد ${fa(s.ram.free_mb)}MB` : "");
    return s;
  } catch {}
}

/* ── صفحه‌بندی و رویدادها ── */
function pagerInfo(id, total, p, per) {
  const pages = Math.max(1, Math.ceil(total / per));
  $("#" + id).textContent = `صفحه ${fa(p)} از ${fa(pages)} — ${fa(total)} رکورد`;
}
function step(which, d) { page[which] = Math.max(1, page[which] + d); load(which === "invoices" ? "invoices" : which); }

document.addEventListener("click", async (e) => {
  const btn = e.target.closest("[data-act]");
  if (!btn) return;
  const act = btn.dataset.act, id = btn.dataset.id, code = btn.dataset.code;
  if (act === "close-modal") return closeModal();
  if (act === "users-prev") return step("users", -1);
  if (act === "users-next") return step("users", 1);
  if (act === "inv-prev") return step("invoices", -1);
  if (act === "inv-next") return step("invoices", 1);
  if (act === "runs-prev") return step("runs", -1);
  if (act === "runs-next") return step("runs", 1);
  if (act === "err-prev") return step("errors", -1);
  if (act === "err-next") return step("errors", 1);
  if (act === "notice-prev") return step("notices", -1);
  if (act === "notice-next") return step("notices", 1);
  if (act === "case-prev") return step("cases", -1);
  if (act === "case-next") return step("cases", 1);
  if (act === "sup-prev") return step("support", -1);
  if (act === "sup-next") return step("support", 1);
  if (act === "search-support") { page.support = 1; return loadSupport(); }
  if (act === "search-users") { page.users = 1; return loadUsers(); }
  if (act === "search-inv") { page.invoices = 1; return loadInvoices(); }
  if (act === "search-runs") { page.runs = 1; return loadRuns(); }
  if (act === "search-notices") { page.notices = 1; return loadNotices(); }
  if (act === "user") return openUser(+id);
  if (act === "inv-ok") return confirmModal("تأیید فاکتور " + code, "<p>پلن کاربر فعال و پیام تأیید برایش ارسال می‌شود. مطمئنید؟</p>", async () => {
    const r = await api(`/invoices/${code}/approve`, { method: "POST", body: {} });
    toast(r.kind === "turn" ? "فاکتور نوبت تأیید شد" : "فاکتور تأیید شد ✅");
    loadInvoices();
  });
  if (act === "inv-no") return promptModal("رد فاکتور " + code, "دلیل رد (به کاربر ارسال می‌شود):", async (val) => {
    if (!val.trim()) { toast("دلیل رد لازم است", "warn"); return false; }
    await api(`/invoices/${code}/reject`, { method: "POST", body: { reason: val } });
    toast("فاکتور رد شد"); loadInvoices(); return true;
  }, "مثال: تصویر رسید خوانا نیست");
  if (act === "inv-short") return promptModal("اعلام کسری " + code, `مبلغ کسری (تومان — فاکتور ${fa(+btn.dataset.amt)} ت):`, async (val) => {
    const amt = Number(val.replace(/[^0-9]/g, ""));
    if (!amt) { toast("مبلغ نامعتبر است", "warn"); return false; }
    await api(`/invoices/${code}/shortfall`, { method: "POST", body: { amount: amt } });
    toast("کسری برای کاربر اعلام شد"); loadInvoices(); return true;
  }, "مثال: 150000");
  if (act === "add-beta") {
    const v = $("#betaAdd").value.replace(/[^0-9]/g, "");
    if (!v) return toast("آیدی عددی لازم است", "warn");
    await api("/beta", { method: "POST", body: { bale_id: +v } });
    $("#betaAdd").value = ""; toast("به بتا اضافه شد"); return loadBeta();
  }
  if (act === "del-beta") {
    await api(`/beta/${id}`, { method: "DELETE" }); toast("از بتا حذف شد"); return loadBeta();
  }
  if (act === "send-broadcast") {
    const text = $("#bcText").value.trim();
    if (!text) return toast("متن پیام خالی است", "warn");
    const tgt = $("#bcTarget").value, n = { all: "همه کاربران", active: "کاربران فعال", paid: "پرداختی‌ها", free: "رایگان‌ها", beta: "بتا" }[tgt];
    return confirmModal("ارسال همگانی", `<p>پیام به <b>${n}</b> ارسال شود؟ (قابل بازگشت نیست)</p><blockquote>${esc(text).slice(0, 300)}</blockquote>`, async () => {
      btn.disabled = true; $("#bcResult").textContent = "در حال ارسال…";
      try {
        const r = await api("/broadcast", { method: "POST", body: { text, target: tgt } });
        $("#bcResult").textContent = `ارسال شد: ${fa(r.sent)} · ناموفق: ${fa(r.failed)} از ${fa(r.total)}`;
        toast("پیام همگانی ارسال شد 📡");
      } finally { btn.disabled = false; }
    });
  }
  if (act === "send-dm") {
    const uid = Number($("#dmUser").value.replace(/[^0-9]/g, ""));
    const text = $("#dmText").value.trim();
    if (!uid || !text) return toast("آیدی و متن لازم است", "warn");
    btn.disabled = true;
    try {
      await api(`/users/${uid}/message`, { method: "POST", body: { text } });
      $("#dmResult").textContent = "پیام به کاربر " + fa(uid) + " ارسال شد.";
      toast("پیام ارسال شد ✅"); $("#dmText").value = "";
    } catch (e) { $("#dmResult").textContent = e.message; } finally { btn.disabled = false; }
    return;
  }
});

/* اینتر در جستجوها */
document.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.target === $("#userSearch")) { page.users = 1; loadUsers(); }
  if (e.target === $("#invSearch")) { page.invoices = 1; loadInvoices(); }
  if (e.target === $("#noticeSearch")) { page.notices = 1; loadNotices(); }
  if (e.target === $("#supSearch")) { page.support = 1; loadSupport(); }
});
["userPlan", "userStatus"].forEach(id => $("#" + id).addEventListener("change", () => { page.users = 1; loadUsers(); }));
$("#invStatus").addEventListener("change", () => { page.invoices = 1; loadInvoices(); });
$("#runStatus").addEventListener("change", () => { page.runs = 1; loadRuns(); });

/* ── مودال‌ها ── */
function openModal(title, bodyHtml) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = bodyHtml;
  $("#modal").classList.remove("hidden");
}
function closeModal() { $("#modal").classList.add("hidden"); $("#modalBody").innerHTML = ""; }
$("#modal").addEventListener("click", (e) => { if (e.target.id === "modal") closeModal(); });

function confirmModal(title, bodyHtml, onOk) {
  openModal(title, bodyHtml + `<div style="display:flex;gap:10px;margin-top:16px">
    <button class="btn btn-primary" id="mOk">بله، انجام بده</button>
    <button class="btn" data-act="close-modal">انصراف</button></div>`);
  $("#mOk").onclick = async () => { try { await onOk(); } catch {} closeModal(); };
}
function promptModal(title, label, onOk, placeholder) {
  openModal(title, `<label style="color:var(--mut)">${label}</label>
    <input class="in" id="mVal" placeholder="${esc(placeholder || "")}" style="margin-top:8px">
    <div style="display:flex;gap:10px;margin-top:14px">
    <button class="btn btn-primary" id="mOk">ثبت</button>
    <button class="btn" data-act="close-modal">انصراف</button></div>`);
  const inp = $("#mVal"); inp.focus();
  inp.onkeydown = async (e) => { if (e.key === "Enter") { e.preventDefault(); $("#mOk").click(); } };
  $("#mOk").onclick = async () => { try { if (await onOk(inp.value)) closeModal(); } catch {} };
}

/* ── جزئیات کاربر ── */
async function openUser(uid) {
  const d = await api(`/users/${uid}`);
  const s = d.sub || {};
  const [stt, stc] = STATUS_FA[s.status] || [s.status || "بدون اشتراک", ""];
  const quota = s.quota_total > 0 ? `${fa(s.quota_used)} از ${fa(s.quota_total)}` : "—";
  openModal(`کاربر ${uid} — ${d.user.first_name || ""}`, `
    <div class="dl-grid">
      <div>
        <h4>اشتراک</h4>
        <div class="row"><span>وضعیت</span><span>${tag(stt, stc)}</span></div>
        <div class="row"><span>پلن</span><span>${s.plan ? esc(PLAN_FA[s.plan] || s.plan) + " " + (s.cycle === "quarterly" ? "(۳ ماهه)" : s.cycle === "monthly" ? "(ماهانه)" : "") : "—"}</span></div>
        <div class="row"><span>اعتبار استعلام</span><span>${fa(s.inquiries_left ?? 0)}</span></div>
        <div class="row"><span>سهمیه ماه</span><span>${quota}</span></div>
        <div class="row"><span>تا تاریخ</span><span>${s.paid_until_fa || "—"}</span></div>
        <div class="row"><span>موبایل</span><span>${esc(s.phone || "—")}</span></div>
        <div class="row"><span>شروع رایگان مصرف‌شده</span><span>${s.free_used ? "بله" : "خیر"}</span></div>
        <div class="row"><span>محدودیت</span><span>${s.restricted_until ? (s.restricted_until_fa + " — " + esc(s.restriction_reason || "")) : "—"}</span></div>
        <div class="row"><span>بتا</span><span>${d.beta ? "عضو" : "—"}</span></div>
        <div style="display:flex;gap:8px;margin-top:12px">
          ${s.restricted_until ? `<button class="btn" data-act="unrestrict" data-id="${uid}">برداشتن محدودیت</button>`
        : `<button class="btn btn-danger" data-act="restrict" data-id="${uid}">محدودسازی (قاعده ۶)</button>`}
        </div>
      </div>
      <div>
        <h4>فاکتورهای اخیر</h4>
        ${d.invoices.map(i => { const [t, c] = INV_STATUS_FA[i.status] || [i.status, ""]; return `<div class="row"><span>${esc(i.code)} · ${esc(KIND_FA[i.kind] || i.kind)} · ${fa(i.amount_toman)} ت</span><span>${tag(t, c)}</span></div>`; }).join("") || `<p class="empty">ندارد</p>`}
        <h4>پرونده‌های پیگیری (${fa(d.cases.length)})</h4>
        ${d.cases.map(c => `<div class="row"><span>${esc(c.case_number)}</span><span>${c.portal === "lawyer" ? "وکیل" : "شخص"}</span></div>`).join("") || `<p class="empty">ندارد</p>`}
      </div>
    </div>
    <h4>رویدادهای پلن</h4>
    ${d.events.map(ev => `<div class="row"><span>${ev.created_at_fa || "—"}</span><span>${esc(EV_FA[ev.event] || ev.event)} — ${esc(ev.detail || "")}</span></div>`).join("") || `<p class="empty">ندارد</p>`}`);
  /* دکمه‌های محدودیت داخل مودال */
  $("#modalBody").addEventListener("click", async (ev) => {
    const b = ev.target.closest("[data-act=restrict],[data-act=unrestrict]");
    if (!b || b.dataset.bound) return;
    b.dataset.bound = "1";
    if (b.dataset.act === "unrestrict") {
      await api(`/users/${b.dataset.id}/unrestrict`, { method: "POST", body: {} });
      toast("محدودیت برداشته شد"); closeModal(); openUser(uid); return;
    }
    promptModal(`محدودسازی کاربر ${uid}`, "مدت (ساعت) و دلیل (با خط تیره جدا کنید):", async (val) => {
      const m = val.match(/^\s*(\d+)\s*-\s*(.*)$/);
      if (!m) { toast("قالب: 24 - دلیل", "warn"); return false; }
      await api(`/users/${uid}/restrict`, { method: "POST", body: { hours: +m[1], reason: m[2] || "قاعده ۶" } });
      toast("کاربر محدود شد"); closeModal(); openUser(uid); return true;
    }, "24 - مصرف غیرعادی");
  }, { once: true });
}

/* ── شروع ── */
loadSys(); tryResume();
