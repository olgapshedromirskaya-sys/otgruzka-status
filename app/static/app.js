const state = {
  currentMarketplace: "wb",
  currentPage: "dashboard",
};

const summaryCards = document.getElementById("summaryCards");
const ordersList = document.getElementById("ordersList");
const refreshBtn = document.getElementById("refreshBtn");
const syncBtn = document.getElementById("syncBtn");
const searchInput = document.getElementById("searchInput");
const orderTemplate = document.getElementById("orderTemplate");
const tabs = document.querySelectorAll(".tab");
const pageTabs = document.querySelectorAll(".page-tab");
const dashboardPage = document.getElementById("dashboardPage");
const settingsPage = document.getElementById("settingsPage");
const settingsForm = document.getElementById("settingsForm");
const exportCsvBtn = document.getElementById("exportCsvBtn");
const exportXlsxBtn = document.getElementById("exportXlsxBtn");

const STATUS_SEVERITY = {
  buyout: "good",
  rejection: "bad",
  defect: "bad",
  return_started: "warn",
  return_in_transit_from_buyer: "warn",
  return_arrived_to_seller_pickup: "warn",
};

let searchDebounce = null;

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: {
      "Content-Type": "application/json",
      ...(options.headers || {}),
    },
    ...options,
  });
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw new Error(payload.detail || "Ошибка API");
  }
  return response.json();
}

function formatDate(isoDate) {
  if (!isoDate) return "—";
  return new Date(isoDate).toLocaleString("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function summaryCard(label, value, note = "") {
  return `
    <article class="metric-card">
      <p class="label">${label}</p>
      <p class="value">${value}</p>
      ${note ? `<p class="note">${note}</p>` : ""}
    </article>
  `;
}

function setPage(page) {
  state.currentPage = page;
  pageTabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.page === page));
  dashboardPage.classList.toggle("hidden", page !== "dashboard");
  settingsPage.classList.toggle("hidden", page !== "settings");
}

function setMarketplace(marketplace) {
  state.currentMarketplace = marketplace;
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.marketplace === marketplace));
}

function renderSummary(summary) {
  const baseCards = [
    summaryCard("Заказов в базе", summary.total_orders),
    summaryCard("Обновлено сегодня", summary.updated_today),
  ];
  const statusCards = Object.entries(summary.by_status || {}).map(([statusName, count]) =>
    summaryCard(statusName, count)
  );
  summaryCards.innerHTML = [...baseCards, ...statusCards].join("");
}

function renderEventItem(event) {
  return `
    <div class="event-item">
      <strong>${event.status_name}</strong> — ${formatDate(event.event_at)}
      ${event.note ? `<br/>${event.note}` : ""}
    </div>
  `;
}

function renderOrders(items) {
  ordersList.innerHTML = "";
  if (!items.length) {
    ordersList.innerHTML = `<div class="empty">Заказы не найдены.</div>`;
    return;
  }

  for (const order of items) {
    const fragment = orderTemplate.content.cloneNode(true);
    const title = fragment.querySelector(".order-title");
    const subtitle = fragment.querySelector(".order-subtitle");
    const pill = fragment.querySelector(".status-pill");
    const timeline = fragment.querySelector(".timeline");

    title.textContent = `Сборочное задание №${order.assembly_task_number}`;
    subtitle.textContent = `${order.marketplace_name} • ${order.product_name} • SKU: ${order.sku || "—"} • Кол-во: ${
      order.quantity
    }`;
    pill.textContent = `${order.current_status_name} · ${formatDate(order.current_status_at)}`;
    pill.classList.add(STATUS_SEVERITY[order.current_status] || "");

    timeline.innerHTML = order.events.length
      ? order.events.map((event) => renderEventItem(event)).join("")
      : `<div class="event-item">История статусов пока пуста.</div>`;

    ordersList.appendChild(fragment);
  }
}

async function loadSummary() {
  const summary = await api(`/api/dashboard/${state.currentMarketplace}`);
  renderSummary(summary);
}

async function loadOrders() {
  const search = searchInput.value.trim();
  const query = new URLSearchParams({
    marketplace: state.currentMarketplace,
    limit: "200",
  });
  if (search) query.set("search", search);
  const payload = await api(`/api/orders?${query.toString()}`);
  renderOrders(payload.items || []);
}

async function loadSettings() {
  const payload = await api("/api/settings");
  settingsForm.wb_token.value = payload.wb_token || "";
  settingsForm.ozon_client_id.value = payload.ozon_client_id || "";
  settingsForm.ozon_api_key.value = payload.ozon_api_key || "";
}

async function saveSettings() {
  const data = new FormData(settingsForm);
  const submitButton = settingsForm.querySelector("button[type='submit']");
  submitButton.disabled = true;
  try {
    await api("/api/settings", {
      method: "PUT",
      body: JSON.stringify({
        wb_token: data.get("wb_token") || "",
        ozon_client_id: data.get("ozon_client_id") || "",
        ozon_api_key: data.get("ozon_api_key") || "",
      }),
    });
    alert("Настройки сохранены.");
  } finally {
    submitButton.disabled = false;
  }
}

async function runSync() {
  syncBtn.disabled = true;
  try {
    const report = await api("/api/sync/run", { method: "POST" });
    alert(
      `${report.message}\nWB: ${report.wb_received}\nOzon: ${report.ozon_received}\nОбработано: ${report.processed_orders}`
    );
    await reloadDashboard();
  } finally {
    syncBtn.disabled = false;
  }
}

function exportCsv() {
  window.location.href = "/api/export/orders.csv";
}

function exportXlsx() {
  window.location.href = "/api/export/orders.xlsx";
}

async function reloadDashboard() {
  await Promise.all([loadSummary(), loadOrders()]);
}

function bindEvents() {
  tabs.forEach((tab) => {
    tab.addEventListener("click", async () => {
      setMarketplace(tab.dataset.marketplace);
      await reloadDashboard();
    });
  });

  pageTabs.forEach((tab) => {
    tab.addEventListener("click", async () => {
      setPage(tab.dataset.page);
      if (tab.dataset.page === "settings") {
        await loadSettings();
      }
    });
  });

  refreshBtn.addEventListener("click", () => {
    reloadDashboard().catch((error) => alert(error.message));
  });

  syncBtn.addEventListener("click", () => {
    runSync().catch((error) => alert(error.message));
  });

  searchInput.addEventListener("input", () => {
    if (searchDebounce) clearTimeout(searchDebounce);
    searchDebounce = setTimeout(() => {
      loadOrders().catch((error) => alert(error.message));
    }, 250);
  });

  settingsForm.addEventListener("submit", (event) => {
    event.preventDefault();
    saveSettings().catch((error) => alert(error.message));
  });

  exportCsvBtn.addEventListener("click", exportCsv);
  exportXlsxBtn.addEventListener("click", exportXlsx);
}

async function bootstrap() {
  setMarketplace("wb");
  setPage("dashboard");
  bindEvents();
  await reloadDashboard();
}

bootstrap().catch((error) => {
  summaryCards.innerHTML = `<div class="empty">Ошибка загрузки: ${error.message}</div>`;
});
