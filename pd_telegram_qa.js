const telegram = window.Telegram?.WebApp;
const submit = document.getElementById("submit-trip");
const result = document.getElementById("result");

if (telegram?.initData) {
    telegram.ready();
    const headers = {"X-Telegram-Init-Data": telegram.initData};
    const statuses = {requested: "Ожидает назначения", assigned: "Тестовый пилот назначен"};
    let saved = false;
    let busy = false;

    function show(trip) {
        saved = Boolean(trip);
        submit.hidden = saved;
        submit.disabled = busy || saved;
        result.textContent = trip
            ? `Заявка №9900000000000000001. Статус: ${statuses[trip.status] ?? "Статус обновлён"}.`
            : "Готово к отправке.";
    }

    async function refresh() {
        try {
            const response = await fetch("/preview/telegram-miniapp/status", {headers});
            if (response.status === 403) {
                submit.disabled = true;
                result.textContent = "Этот тест доступен аккаунту диспетчера.";
                return;
            }
            if (!response.ok) throw new Error();
            const data = await response.json();
            if (!busy) show(data.trip);
        } catch {
            result.textContent = "Не удалось проверить статус. Открой мини-приложение заново.";
        }
    }

    submit.addEventListener("click", async () => {
        busy = true;
        submit.disabled = true;
        result.textContent = "Отправляю тестовую заявку…";
        try {
            const response = await fetch("/preview/telegram-miniapp", {method: "POST", headers});
            const data = await response.json();
            if (!response.ok || data.qa_only !== true || !data.trip?.id) throw new Error();
            show(data.trip);
        } catch {
            result.textContent = "Заявка не подтверждена. Повтори отправку или открой страницу заново.";
        } finally {
            busy = false;
            submit.disabled = saved;
        }
    });
    refresh();
    setInterval(() => { if (saved && !busy && !document.hidden) refresh(); }, 5000);
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden && !busy) refresh();
    });
}
