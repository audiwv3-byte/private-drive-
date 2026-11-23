(() => {
  'use strict';

  const endpoint = 'https://private-drive-dispatcher-staging.onrender.com/site-events';
  const preference = 'pd-site-analytics-v1';
  const sessionKey = 'pd-site-visit-v1';
  const label = /^[a-z0-9][a-z0-9_.-]{0,47}$/i;
  const page = location.pathname.replace(/^\/index\.html$/, '/');
  let storage;
  try {
    storage = { choices: window.localStorage, visits: window.sessionStorage };
    storage.choices.getItem(preference);
  } catch (_) { return; }

  function attribution() {
    const params = new URLSearchParams(location.search);
    const tag = params.get('utm_source');
    const campaign = params.get('utm_campaign');
    let source = 'direct';
    if (tag && label.test(tag)) {
      source = tag;
    } else if (document.referrer) {
      try {
        const referrer = new URL(document.referrer);
        if (referrer.origin !== location.origin && label.test(referrer.hostname)) {
          source = referrer.hostname;
        }
      } catch (_) {}
    }
    return { source, campaign: campaign && label.test(campaign) ? campaign : '' };
  }

  function visit() {
    const now = Date.now();
    const stored = JSON.parse(storage.visits.getItem(sessionKey) || 'null');
    const current = stored && now - stored.seen < 30 * 60 * 1000
      ? stored : { visit: crypto.randomUUID().replaceAll('-', ''), ...attribution() };
    current.seen = now;
    storage.visits.setItem(sessionKey, JSON.stringify(current));
    return current;
  }

  function send(event) {
    try {
      if (storage.choices.getItem(preference) !== 'allow') return;
      const { visit: id, source, campaign } = visit();
      fetch(endpoint, {
        method: 'POST', keepalive: true, credentials: 'omit',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ visit: id, page, event, source, campaign }),
      }).catch(() => {});
    } catch (_) {}
  }

  function viewed() {
    send('view');
    if (page === '/order-map.html') send('booking');
  }

  const panel = document.createElement('aside');
  panel.className = 'pd-analytics-consent';
  panel.setAttribute('aria-label', 'Аналитика сайта');
  panel.innerHTML = '<p>Разрешишь аналитику посещений? Учитываем страницы, источник перехода и открытие формы заказа.</p>' +
    '<button type="button" data-analytics="allow">Разрешить</button> ' +
    '<button type="button" data-analytics="deny">Отклонить</button> ' +
    '<a href="/privacy.html#site-analytics">Подробнее</a>';
  const settings = document.createElement('button');
  settings.className = 'pd-analytics-settings';
  settings.type = 'button';
  settings.textContent = 'Настройки аналитики';
  settings.addEventListener('click', () => {
    panel.hidden = false;
    panel.querySelector('button').focus();
  });
  panel.addEventListener('click', event => {
    const choice = event.target.dataset.analytics;
    if (choice !== 'allow' && choice !== 'deny') return;
    try {
      const previous = storage.choices.getItem(preference);
      storage.choices.setItem(preference, choice);
      panel.hidden = true;
      if (choice === 'deny') storage.visits.removeItem(sessionKey);
      else if (previous !== 'allow') viewed();
      settings.focus();
    } catch (_) { panel.hidden = true; }
  });
  panel.hidden = !!storage.choices.getItem(preference);
  document.body.append(settings, panel);
  window.pdSiteEvent = send;
  viewed();
})();
