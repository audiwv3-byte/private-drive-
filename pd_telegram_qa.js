const telegram = window.Telegram?.WebApp;
const submit = document.getElementById("submit-trip");
const result = document.getElementById("result");

if (telegram?.initData) {
    telegram.ready();
    submit.disabled = false;
    result.textContent = "Готово к отправке.";
    submit.addEventListener("click", async () => {
        submit.disabled = true;
        result.textContent = "Отправляю тестовую заявку…";
        try {
            const response = await fetch("/preview/telegram-miniapp", {
                method: "POST",
                headers: {"X-Telegram-Init-Data": telegram.initData},
            });
            const data = await response.json();
            if (!response.ok || data.qa_only !== true || !data.trip?.id) {
                throw new Error("Test request failed");
            }
            result.textContent = `Заявка 9900000000000000001 в тестовой очереди. ID: ${data.trip.id}`;
        } catch {
            result.textContent = "Ответ не получен. Открой приложение заново или повтори отправку.";
        } finally {
            submit.disabled = false;
        }
    });
}
