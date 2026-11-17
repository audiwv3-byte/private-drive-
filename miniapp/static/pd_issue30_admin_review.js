/* PRIVATE DRIVE issue #30: opt-in admin document review panel.
 * NOT mounted in production. Invoke mountIssue30Review(host, applicantId,
 * initData) only after admin cabinet integration + separate deployment review.
 * No HTML injection, no client-side role trust, no confidential data storage.
 */
export async function mountIssue30Review(host, applicantId, initData) {
  if (!(host instanceof Element) || !Number.isSafeInteger(applicantId) || applicantId <= 0) {
    throw new TypeError("Invalid admin document review target");
  }
  if (typeof initData !== "string" || !initData) {
    throw new TypeError("Telegram session verification required");
  }
  const root = "/api/admin/driver-applications/" + applicantId;
  const headers = { "X-Telegram-Init-Data": initData };
  const sides = [
    ["license_front", "Права — лицевая сторона"],
    ["license_back", "Права — обратная сторона"],
    ["car_front", "Авто — спереди"],
    ["car_rear", "Авто — сзади"],
    ["car_interior", "Авто — салон"],
    ["registration_front", "Техпаспорт — лицевая сторона"],
    ["registration_back", "Техпаспорт — обратная сторона (необязательно)"],
    ["ltsa", "LTSA"],
    ["activity", "Индивидуальная деятельность"],
    ["insurance", "Страховка"],
    ["portrait", "Фото пилота"],
  ];
  function element(tag, text) {
    const node = document.createElement(tag);
    if (text != null) node.textContent = String(text);
    return node;
  }
  async function request(url, options = {}) {
    const response = await fetch(url, {
      credentials: "same-origin",
      cache: "no-store",
      ...options,
      headers: {...headers, ...(options.headers || {})},
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(payload.error || "Ошибка запроса");
    return payload;
  }
  host.classList.add('pd-issue30-panel');
  host.replaceChildren();
  const heading = element("h3", "Документы пилота — индивидуальная проверка");
  const notice = element("p", "Статусы загружаются из сервера");
  notice.setAttribute("role", "status");
  const grid = element("div");
  host.append(heading, notice, grid);
  async function refresh() {
    const response = await request(root + "/document-reviews");
    grid.replaceChildren();
    for (const [side, label] of sides) {
      const state = response.documents?.[side] || {status: "missing"};
      const row = element("div");
      row.className = 'pd-issue30-document';
      const description = element("span", label + " — " + state.status);
      description.className = 'pd-issue30-document-title';
      const preview = element("button", "Просмотреть");
      preview.disabled = state.status === "missing";
      preview.addEventListener("click", async () => {
        try {
          // Protected document GET requires the server-validated Telegram header.
          const res = await fetch(
            "/api/driver/documents/" + applicantId + "/" + encodeURIComponent(side),
            {headers, credentials:"same-origin", cache:"no-store"}
          );
          if (!res.ok) throw new Error("Документ недоступен");
          const blob = await res.blob();
          if (blob.type !== "image/jpeg") throw new Error("Неверный тип документа");
          const objectUrl = URL.createObjectURL(blob);
          const anchor = document.createElement("a");
          anchor.href = objectUrl;
          anchor.target = "_blank";
          anchor.rel = "noopener noreferrer";
          anchor.click();
          setTimeout(() => URL.revokeObjectURL(objectUrl), 30000);
        } catch (err) {
          notice.textContent = err.message;
        }
      });
      const reason = element("input");
      reason.setAttribute('aria-label', label + ': причина отклонения');
      reason.placeholder = "Причина отклонения";
      reason.maxLength = 500;
      const approve = element("button", "Одобрить");
      const reject = element("button", "Отклонить");
      const replaceInput = element("input");
      replaceInput.setAttribute("aria-label", label + ": файл замены");
      replaceInput.type = "file";
      replaceInput.accept = "image/jpeg,image/png,image/webp";
      const replace = element("button", "Заменить документ");
      const active = typeof state.sha256 === "string" && /^[0-9a-f]{64}$/.test(state.sha256);
      approve.disabled = !active;
      reject.disabled = !active;
      replace.disabled = !active;
      async function submitDecision(status) {
        for (const b of [approve, reject, replace]) b.disabled = true;
        try {
          await request(root + "/document-reviews/" + encodeURIComponent(side), {
            method: "POST", headers: {"Content-Type": "application/json"},
            body: JSON.stringify({status,sha256:state.sha256,reason:reason.value}),
          });
          await refresh();
        } catch (err) {
          notice.textContent = err.message;
          for (const b of [approve, reject, replace]) b.disabled = !active;
        }
      }
      approve.addEventListener("click", () => submitDecision("approved"));
      reject.addEventListener("click", () => submitDecision("rejected"));
      replace.addEventListener("click", async () => {
        const file = replaceInput.files?.[0];
        if (!file) { notice.textContent = "Выбери фотографию"; return; }
        for (const b of [approve, reject, replace]) b.disabled = true;
        try {
          const data = new FormData();
          data.set(side, file);
          data.set("expected_sha256",state.sha256);
          await request(root + "/documents/" + encodeURIComponent(side) + "/replace",
                        {method:"POST",body:data});
          await refresh();
        } catch (err) { notice.textContent = err.message; replace.disabled = !active; }
      });
      row.append(description, preview, reason, approve, reject, replaceInput, replace);
      grid.append(row);
    }
    notice.textContent = "Проверяй каждую сторону документа отдельно";
    host.dispatchEvent(new CustomEvent('pd-issue30-review-updated', {bubbles:true}));
  }
  try {
    await refresh();
  } catch (err) {
    notice.textContent = err.message || 'Не удалось загрузить документы';
  }
  return {refresh};
}
