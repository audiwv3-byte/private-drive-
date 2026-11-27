(() => {
  'use strict';

  const panel = document.getElementById('pdFirstRideWheel');
  if (!panel) return;
  const telegram = panel.dataset.channel === 'telegram';
  const endpoint = telegram ? '/api/first-ride-wheel' : '/preview/api/first-ride-wheel';
  const status = panel.querySelector('[role="status"]');
  const wheel = panel.querySelector('.pd-wheel-disc');
  const spin = panel.querySelector('[data-wheel-spin]');
  const book = panel.querySelector('[data-wheel-book]');
  const form = panel.querySelector('form');
  const phone = form.elements.phone;
  const code = form.elements.code;
  const submit = form.querySelector('button');
  let token = '';
  let challenge = '';
  let busy = false;

  // Website bookings can use the verified session for the current page.
  window.pdFirstRideBookingHeaders = () => token ? { Authorization: 'Bearer ' + token } : {};

  async function api(path = '', body) {
    const headers = { 'Content-Type': 'application/json', ...window.pdFirstRideBookingHeaders() };
    if (telegram) headers['X-Telegram-Init-Data'] = window.Telegram?.WebApp?.initData || '';
    const response = await fetch(endpoint + path, {
      method: body === undefined ? 'GET' : 'POST',
      credentials: 'same-origin', cache: 'no-store', headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    if (!response.ok) throw Error(String(response.status));
    return response.json();
  }

  function wheelAngle(percent) {
    const sector = { 5: 0, 10: 1, 15: 2, 20: 3 }[percent];
    return sector === undefined ? 0 : -sector * 90;
  }

  function show(reward) {
    wheel.getAnimations().forEach(animation => animation.cancel());
    wheel.style.transform = `rotate(${wheelAngle(reward.percent)}deg)`;
    panel.hidden = false;
    form.hidden = !['sign_in_required', 'link_required'].includes(reward.state);
    spin.hidden = reward.state !== 'ready';
    book.hidden = reward.state !== 'available';
    const until = reward.expires_at
      ? new Intl.DateTimeFormat('ru', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Europe/Vilnius' })
        .format(reward.expires_at * 1000)
      : '';
    const copy = {
      sign_in_required: 'Подтверди номер, чтобы открыть колесо.',
      link_required: 'Подтверди номер, чтобы привязать Telegram к аккаунту.',
      ready: 'Один бесплатный прокрут. Скидка от 5% до 20%.',
      available: `Твоя скидка — ${reward.percent}%. Действует до ${until}.`,
      used: `Скидка ${reward.percent}% уже применена.`,
      expired: 'Срок скидки истёк.',
      ineligible: 'Колесо доступно до первого заказа.',
    };
    status.textContent = copy[reward.state] || 'Колесо временно недоступно.';
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy) return;
    busy = true;
    submit.disabled = true;
    try {
      if (!challenge) {
        const result = await api('/phone/request-code', { channel: 'phone', destination: phone.value });
        challenge = result.challenge_id;
        phone.readOnly = true;
        code.closest('label').hidden = false;
        code.required = true;
        submit.textContent = 'Подтвердить номер';
        code.focus();
        status.textContent = 'Введи одноразовый код.';
      } else {
        const result = await api('/phone/verify-code', { challenge_id: challenge, code: code.value });
        token = result.access_token || '';
        if (!telegram && token) {
          for (const field of document.querySelectorAll('#quick-phone, #pickup-phone')) {
            field.value = phone.value;
            field.readOnly = true;
          }
        }
        show(await api());
      }
    } catch (error) {
      if (challenge && error.message === '401') {
        challenge = '';
        phone.readOnly = false;
        code.value = '';
        code.required = false;
        code.closest('label').hidden = true;
        submit.textContent = 'Получить код';
        status.textContent = 'Код не подошёл. Запроси новый, когда закончится пауза.';
      } else {
        status.textContent = error.message === '409'
          ? 'Этот Telegram уже связан с другим аккаунтом.'
          : 'Не удалось подтвердить номер. Попробуй ещё раз.';
      }
    } finally {
      busy = false;
      submit.disabled = false;
    }
  });

  spin.addEventListener('click', async () => {
    if (busy) return;
    busy = true;
    spin.disabled = true;
    try {
      const result = await api('', {});
      if (result.state === 'available' && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        await wheel.animate([{ transform: 'rotate(0deg)' },
          { transform: `rotate(${1440 + wheelAngle(result.percent)}deg)` }], {
          duration: 950, easing: 'cubic-bezier(.18,.75,.3,1)', fill: 'forwards',
        }).finished;
      }
      show(result);
    } catch (_) {
      status.textContent = 'Не удалось обновить скидку. Попробуй ещё раз.';
    } finally {
      busy = false;
      spin.disabled = false;
    }
  });

  book.addEventListener('click', () => {
    if (telegram) go(11);
    else document.getElementById('quick-order').scrollIntoView({ block: 'start' });
  });

  if (!telegram || window.Telegram?.WebApp?.initData) api().then(show).catch(() => {});
})();
