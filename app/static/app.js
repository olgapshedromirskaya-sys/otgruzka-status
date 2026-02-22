const state = {
  currentMarketplace: "wb",
  statuses: [],
  statusMap: {},
};

const summaryCards = document.getElementById("summaryCards");
const ordersList = document.getElementById("ordersList");
const createOrderForm = document.getElementById("createOrderForm");
const refreshBtn = document.getElementById("refreshBtn");
const statusFilter = document.getElementById("statusFilter");
const searchInput = document.getElementById("searchInput");
const orderTemplate = document.getElementById("orderTemplate");
const tabs = document.querySelectorAll(".tab");

const STATUS_SEVERITY = {
  buyout: "good",
  rejection: "bad",
  defect: "bad",
  return_started: "warn",
  return_in_transit_from_buyer: "warn",
  return_arrived_to_seller_pickup: "warn",
  warehouse_handover: "good",
  sorted: "good",
  in_transit_to_buyer_pickup: "good",
  arrived_at_buyer_pickup: "good",
};

function toIso(inputValue) {
  if (!inputValue) return null;
  return new Date(inputValue).toISOString();
}

function formatDate(isoDate) {
  if (!isoDate) return "—";
  return new Date(isoDate).toLocaleString("ru-RU", {
    dateStyle: "short",
    timeStyle: "short",
  });
}

function nowLocalInputValue() {
  const date = new Date();
  const tzOffsetMinutes = date.getTimezoneOffset();
  const local = new Date(date.getTime() - tzOffsetMinutes * 60 * 1000);
  return local.toISOString().slice(0, 16);
}

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

function summaryCard(label, value, note = "") {
  return `
    <article class="metric-card">
      <p class="label">${label}</p>
      <p class="value">${value}</p>
      ${note ? `<p class="note">${note}</p>` : ""}
    </article>
  `;
}

async function loadMeta() {
  state.statuses = await api("/api/meta/statuses");
  state.statusMap = state.statuses.reduce((acc, item) => {
    acc[item.code] = item.name;
    return acc;
  }, {});

  for (const status of state.statuses) {
    const option = document.createElement("option");
    option.value = status.code;
    option.textContent = status.name;
    statusFilter.appendChild(option);
  }
}

function setTab(marketplace) {
  state.currentMarketplace = marketplace;
  tabs.forEach((tab) => tab.classList.toggle("active", tab.dataset.marketplace === marketplace));
  createOrderForm.marketplace.value = marketplace;
}

function renderSummary(summary) {
  summaryCards.innerHTML = [
    summaryCard("Заказов всего", summary.total_orders),
    summaryCard("Активные", summary.active_orders),
    summaryCard("Просрочено к отгрузке", summary.overdue_to_ship),
    summaryCard("Выкуп", summary.buyout_count, `${summary.buyout_rate_percent}%`),
    summaryCard("Отказ", summary.rejection_count),
    summaryCard("Возвраты", summary.return_count),
    summaryCard("Брак", summary.defect_count),
    summaryCard(
      "Сборка / сортировка",
      `${summary.by_status.assembly || 0} / ${summary.by_status.sorted || 0}`,
      "по текущим статусам"
    ),
  ].join("");
}

function renderEventItem(event) {
  return `
    <div class="event-item">
      <strong>${state.statusMap[event.status] || event.status}</strong>
      — ${formatDate(event.event_at)}
      ${event.note ? `<br/>${event.note}` : ""}
    </div>
  `;
}

function fillStatusSelect(selectEl) {
  selectEl.innerHTML = state.statuses
    .map((status) => `<option value="${status.code}">${status.name}</option>`)
    .join("");
}

async function submitOrderEvent(orderId, form) {
  const data = new FormData(form);
  await api(`/api/orders/${orderId}/events`, {
    method: "POST",
    body: JSON.stringify({
      status: data.get("status"),
      event_at: toIso(data.get("event_at")),
      note: data.get("note") || null,
    }),
  });
}

function renderOrders(items) {
  ordersList.innerHTML = "";
  if (!items.length) {
    ordersList.innerHTML = `<div class="empty">Нет заказов по выбранным фильтрам.</div>`;
    return;
  }

  for (const order of items) {
    const fragment = orderTemplate.content.cloneNode(true);
    const card = fragment.querySelector(".order-card");
    const title = fragment.querySelector(".order-title");
    const subtitle = fragment.querySelector(".order-subtitle");
    const pill = fragment.querySelector(".status-pill");
    const timeline = fragment.querySelector(".timeline");
    const eventForm = fragment.querySelector(".event-form");
    const statusSelect = eventForm.querySelector("select[name='status']");
    const eventAtInput = eventForm.querySelector("input[name='event_at']");

    title.textContent = `${order.product_name} ×${order.quantity}`;
    subtitle.textContent = `${order.marketplace.toUpperCase()} • №${order.external_order_id} • SKU: ${
      order.sku || "—"
    } • дедлайн сдачи: ${formatDate(order.due_ship_at)}`;
    pill.textContent = `${state.statusMap[order.current_status] || order.current_status} · ${formatDate(
      order.current_status_at
    )}`;
    pill.classList.add(STATUS_SEVERITY[order.current_status] || "");

    timeline.innerHTML = order.events.length
      ? order.events
          .slice()
          .sort((a, b) => new Date(b.event_at) - new Date(a.event_at))
          .map((event) => renderEventItem(event))
          .join("")
      : `<div class="event-item">Нет событий.</div>`;

    fillStatusSelect(statusSelect);
    eventAtInput.value = nowLocalInputValue();
    eventForm.addEventListener("submit", async (event) => {
      event.preventDefault();
      const button = eventForm.querySelector("button");
      button.disabled = true;
      try {
        await submitOrderEvent(order.id, eventForm);
        await reload();
      } catch (error) {
        alert(error.message);
      } finally {
        button.disabled = false;
      }
    });

    card.dataset.orderId = order.id;
    ordersList.appendChild(fragment);
  }
}

async function loadSummary() {
  const summary = await api(`/api/dashboard/${state.currentMarketplace}`);
  renderSummary(summary);
}

async function loadOrders() {
  const search = searchInput.value.trim();
  const status = statusFilter.value;
  const query = new URLSearchParams({ marketplace: state.currentMarketplace, limit: "200" });
  if (search) query.set("search", search);
  if (status) query.set("status", status);
  const payload = await api(`/api/orders?${query.toString()}`);
  renderOrders(payload.items || []);
}

async function reload() {
  await Promise.all([loadSummary(), loadOrders()]);
}

function bindEvents() {
  tabs.forEach((tab) => {
    tab.addEventListener("click", async () => {
      setTab(tab.dataset.marketplace);
      await reload();
    });
  });

  refreshBtn.addEventListener("click", reload);
  searchInput.addEventListener("input", () => {
    loadOrders().catch((error) => alert(error.message));
  });
  statusFilter.addEventListener("change", () => {
    loadOrders().catch((error) => alert(error.message));
  });

  createOrderForm.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(createOrderForm);
    const submitButton = createOrderForm.querySelector("button[type='submit']");
    submitButton.disabled = true;

    try {
      await api("/api/orders", {
        method: "POST",
        body: JSON.stringify({
          marketplace: data.get("marketplace"),
          external_order_id: data.get("external_order_id"),
          product_name: data.get("product_name"),
          sku: data.get("sku") || null,
          quantity: Number(data.get("quantity") || 1),
          due_ship_at: toIso(data.get("due_ship_at")),
          comment: data.get("comment") || null,
          initial_status: "assembly",
          initial_status_at: new Date().toISOString(),
        }),
      });
      createOrderForm.reset();
      createOrderForm.marketplace.value = state.currentMarketplace;
      await reload();
    } catch (error) {
      alert(error.message);
    } finally {
      submitButton.disabled = false;
    }
  });
}

async function bootstrap() {
  await loadMeta();
  setTab("wb");
  bindEvents();
  await reload();
}

bootstrap().catch((error) => {
  summaryCards.innerHTML = `<div class="empty">Ошибка загрузки: ${error.message}</div>`;
});
