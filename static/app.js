const STATUS_CLASS = {
  未着手: "status-todo",
  進行中: "status-doing",
  完了: "status-done",
};

const state = {
  tasks: [],
  assignees: [],
  filters: { assigneeId: "", status: "" },
  editingId: null,
  today: "",
  hasLoaded: false,
};

let refreshToken = 0;

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("add-button").addEventListener("click", () => openTaskDialog(null));
  document.getElementById("cancel-button").addEventListener("click", closeTaskDialog);
  document.getElementById("task-form").addEventListener("submit", onSubmitTask);
  document.getElementById("filter-assignee").addEventListener("change", (event) => {
    state.filters.assigneeId = event.target.value;
    refresh();
  });
  document.getElementById("filter-status").addEventListener("change", (event) => {
    applyStatusFilter(event.target.value);
  });
  document.getElementById("clear-filters").addEventListener("click", () => {
    state.filters.assigneeId = "";
    applyStatusFilter("");
    document.getElementById("filter-assignee").value = "";
  });
  document.querySelectorAll(".stat").forEach((button) => {
    button.addEventListener("click", () => {
      const status = button.dataset.status;
      applyStatusFilter(state.filters.status === status ? "" : status);
    });
  });
  document.getElementById("task-dialog").addEventListener("cancel", (event) => {
    event.preventDefault();
    closeTaskDialog();
  });
  refresh();
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...(options.headers || {}),
    },
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(data.error || "通信に失敗しました");
    error.status = response.status;
    throw error;
  }
  return data;
}

function filtersActive() {
  return Boolean(state.filters.assigneeId || state.filters.status);
}

function applyStatusFilter(status) {
  state.filters.status = status;
  const select = document.getElementById("filter-status");
  if (select.value !== status) select.value = status;
  refresh();
}

async function refresh() {
  const token = ++refreshToken;
  const listParams = new URLSearchParams();
  const countParams = new URLSearchParams();
  if (state.filters.assigneeId) {
    listParams.set("assignee_id", state.filters.assigneeId);
    countParams.set("assignee_id", state.filters.assigneeId);
  }
  if (state.filters.status) listParams.set("status", state.filters.status);

  const listQuery = listParams.toString();
  const countQuery = countParams.toString();
  try {
    const listPromise = api("/api/tasks" + (listQuery ? `?${listQuery}` : ""));
    const countPromise = listQuery === countQuery ? null : api("/api/tasks" + (countQuery ? `?${countQuery}` : ""));
    const assigneePromise = api("/api/assignees");
    const [list, assignees, counts] = await Promise.all([listPromise, assigneePromise, countPromise]);
    if (token !== refreshToken) return;
    state.tasks = list.tasks;
    state.today = list.today;
    state.assignees = assignees.assignees;
    state.hasLoaded = true;
    hideLoadError();
    renderAssignees();
    renderSummary(counts || list);
    renderTasks();
    document.getElementById("live").textContent = `表示 ${list.count} 件`;
  } catch (error) {
    if (token !== refreshToken) return;
    showLoadError(error.message || "読み込めませんでした");
  }
}

function renderAssignees() {
  const select = document.getElementById("filter-assignee");
  const selected = state.filters.assigneeId;
  select.replaceChildren(new Option("すべて", ""));
  state.assignees.forEach((assignee) => {
    select.add(new Option(assignee.name, String(assignee.id)));
  });
  select.value = [...select.options].some((option) => option.value === selected) ? selected : "";
  state.filters.assigneeId = select.value;

  const dataList = document.getElementById("assignee-list");
  dataList.replaceChildren();
  state.assignees.forEach((assignee) => {
    const option = document.createElement("option");
    option.value = assignee.name;
    dataList.append(option);
  });
}

function renderSummary(source) {
  const counts = { 未着手: 0, 進行中: 0, 完了: 0 };
  let overdue = 0;
  source.tasks.forEach((task) => {
    counts[task.status] += 1;
    if (task.overdue) overdue += 1;
  });
  document.querySelectorAll("[data-count]").forEach((node) => {
    node.textContent = String(counts[node.dataset.count] || 0);
  });
  document.querySelectorAll(".stat").forEach((button) => {
    const pressed = button.dataset.status === state.filters.status;
    button.setAttribute("aria-pressed", pressed ? "true" : "false");
  });
  document.getElementById("overdue-note").textContent = overdue
    ? `期限超過が ${overdue} 件あります`
    : "";
  document.getElementById("today-label").textContent = state.today
    ? `今日は ${formatDate(state.today)} です`
    : "";
  document.getElementById("clear-filters").hidden = !filtersActive();
}

function renderTasks() {
  const list = document.getElementById("task-list");
  const status = document.getElementById("list-status");
  const summary = document.getElementById("list-summary");
  list.replaceChildren();

  if (!state.hasLoaded) {
    status.textContent = "読み込み中…";
    summary.textContent = "";
    return;
  }

  summary.textContent = filtersActive()
    ? `${state.tasks.length} 件を表示しています`
    : `タスクは ${state.tasks.length} 件です`;

  if (state.tasks.length === 0) {
    status.textContent = filtersActive()
      ? "条件に合うタスクはありません。"
      : "タスクはまだありません。「タスクを追加」から登録できます。";
    return;
  }

  status.textContent = "";
  state.tasks.forEach((task) => list.append(renderTask(task)));
}

function renderTask(task) {
  const item = document.createElement("li");
  item.className = "task-card";
  if (task.overdue) item.classList.add("is-overdue");
  if (task.status === "完了") item.classList.add("is-done");

  const top = document.createElement("div");
  top.className = "task-top";

  const title = document.createElement("h2");
  title.className = "task-title";
  title.textContent = task.title;

  const badges = document.createElement("div");
  badges.className = "task-top";
  if (task.overdue) {
    const overdue = document.createElement("span");
    overdue.className = "badge badge-overdue";
    overdue.textContent = "期限超過";
    badges.append(overdue);
  }
  const status = document.createElement("span");
  status.className = `status ${STATUS_CLASS[task.status] || ""}`;
  status.textContent = task.status;
  badges.append(status);

  top.append(title, badges);

  const meta = document.createElement("div");
  meta.className = "task-meta";
  const assignee = document.createElement("span");
  assignee.textContent = task.assignee_name ? `担当: ${task.assignee_name}` : "担当者未設定";
  const due = document.createElement("span");
  due.append(document.createTextNode("期限: "));
  if (task.due_date) {
    const time = document.createElement("time");
    time.dateTime = task.due_date;
    time.textContent = formatDate(task.due_date);
    due.append(time);
    if (!task.overdue && task.status !== "完了" && task.due_date === state.today) {
      const mark = document.createElement("span");
      mark.className = "due-warn";
      mark.textContent = "（今日が期限）";
      due.append(mark);
    }
  } else {
    due.append(document.createTextNode("期限なし"));
  }
  meta.append(assignee, due);

  const actions = document.createElement("div");
  actions.className = "card-actions";
  const edit = document.createElement("button");
  edit.type = "button";
  edit.textContent = "編集";
  edit.addEventListener("click", () => openTaskDialog(task));
  const remove = document.createElement("button");
  remove.type = "button";
  remove.textContent = "削除";
  remove.addEventListener("click", () => onDeleteTask(task));
  actions.append(edit, remove);

  item.append(top, meta, actions);
  return item;
}

function formatDate(iso) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || "");
  if (!match) return iso || "";
  return `${match[1]}年${Number(match[2])}月${Number(match[3])}日`;
}

function openTaskDialog(task) {
  const dialog = document.getElementById("task-dialog");
  const form = document.getElementById("task-form");
  const error = document.getElementById("form-error");
  state.editingId = task ? task.id : null;
  form.reset();
  error.hidden = true;
  error.textContent = "";
  document.getElementById("dialog-title").textContent = task ? "タスクを編集" : "タスクを追加";
  document.getElementById("save-button").disabled = false;
  if (task) {
    form.elements.title.value = task.title;
    form.elements.assignee_name.value = task.assignee_name || "";
    form.elements.due_date.value = task.due_date || "";
    form.elements.status.value = task.status;
  } else {
    form.elements.status.value = "未着手";
  }
  if (!dialog.open) dialog.showModal();
  form.elements.title.focus();
}

function closeTaskDialog() {
  const dialog = document.getElementById("task-dialog");
  if (dialog.open) dialog.close();
  state.editingId = null;
}

function showFormError(message) {
  const error = document.getElementById("form-error");
  error.textContent = message;
  error.hidden = false;
}

async function onSubmitTask(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const title = form.elements.title.value.trim();
  if (!title) {
    showFormError("タイトルを入力してください");
    form.elements.title.focus();
    return;
  }

  const payload = {
    title,
    assignee_name: form.elements.assignee_name.value.trim(),
    due_date: form.elements.due_date.value || null,
    status: form.elements.status.value,
  };
  const saveButton = document.getElementById("save-button");
  saveButton.disabled = true;
  try {
    if (state.editingId) {
      await api(`/api/tasks/${state.editingId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
      });
    } else {
      await api("/api/tasks", {
        method: "POST",
        body: JSON.stringify(payload),
      });
    }
    closeTaskDialog();
    await refresh();
  } catch (error) {
    showFormError(error.message || "保存できませんでした");
    saveButton.disabled = false;
  }
}

async function onDeleteTask(task) {
  const dialog = document.getElementById("confirm-dialog");
  document.getElementById("confirm-message").textContent =
    `「${task.title}」を削除します。この操作は取り消せません。`;
  const confirmed = await new Promise((resolve) => {
    dialog.addEventListener("close", () => resolve(dialog.returnValue === "ok"), { once: true });
    dialog.showModal();
  });
  if (!confirmed) return;
  try {
    await api(`/api/tasks/${task.id}`, { method: "DELETE" });
    await refresh();
  } catch (error) {
    showLoadError(error.message || "削除できませんでした");
  }
}

function showLoadError(message) {
  const banner = document.getElementById("load-error");
  banner.hidden = false;
  banner.textContent = message;
  if (!state.hasLoaded) {
    document.getElementById("list-status").textContent = "一覧を表示できません。";
  }
}

function hideLoadError() {
  const banner = document.getElementById("load-error");
  banner.hidden = true;
  banner.textContent = "";
}
