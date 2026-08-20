(() => {
  const list = document.querySelector('.connections-list');
  if (!list) return;

  const requirements = {
    google:
      'Для полной автоматизации нужен Google Cloud project, OAuth-клиент и канал YouTube. Режим «Без приложения» этого не требует.',
    pinterest:
      'Официальный API Pinterest требует business account, зарегистрированное приложение, OAuth и одобренный уровень доступа. Для обычной работы оставьте режим «Без приложения».',
    tiktok:
      'Direct Post требует developer app и Content Posting API; публичная публикация зависит от аудита приложения. В режиме «Без приложения» параметры выбираются на сайте TikTok.',
    meta:
      'Автоматический Instagram требует Professional account, связанную Facebook Page, Meta app и разрешения. Facebook Page publishing также выполняется через Meta app. Ручной пакет работает без этого.',
    vk:
      'Полная автоматизация VK требует приложения и пользовательского access token с нужными правами. Ограниченный ключ сообщества не заменяет весь сценарий публикации с медиа.',
  };

  for (const [provider, text] of Object.entries(requirements)) {
    const card = document.querySelector(`[data-connection-card="${provider}"]`);
    const body = card?.querySelector('.api-mode-body');
    if (!body || body.querySelector('[data-api-requirements]')) continue;
    const note = document.createElement('div');
    note.className = 'api-requirement-note';
    note.dataset.apiRequirements = '';
    const strong = document.createElement('strong');
    strong.textContent = 'Нужно только для автоматического API-режима';
    const paragraph = document.createElement('p');
    paragraph.textContent = text;
    paragraph.style.margin = '6px 0 0';
    note.append(strong, paragraph);
    body.prepend(note);
  }

  if (list.querySelector('[data-connection-card="livemaster"]')) return;

  const card = document.createElement('article');
  card.className = 'connection-panel';
  card.dataset.connectionCard = 'livemaster';

  const header = document.createElement('header');
  header.className = 'connection-panel-head';
  const identity = document.createElement('div');
  identity.className = 'provider-identity';
  const mark = document.createElement('span');
  mark.className = 'provider-mark';
  mark.setAttribute('aria-hidden', 'true');
  mark.textContent = 'ЯМ';
  const copy = document.createElement('div');
  const title = document.createElement('h2');
  title.textContent = 'Ярмарка мастеров';
  const caption = document.createElement('p');
  caption.textContent = 'Карточки товаров через вашу сессию браузера';
  copy.append(title, caption);
  identity.append(mark, copy);
  const state = document.createElement('span');
  state.className = 'connection-state connected';
  const dot = document.createElement('span');
  dot.setAttribute('aria-hidden', 'true');
  state.append(dot, document.createTextNode('Через браузер'));
  header.append(identity, state);

  const actions = document.createElement('div');
  actions.className = 'connection-panel-actions';
  const help = document.createElement('a');
  help.className = 'button primary';
  help.href = '/static/help.html#livemaster-browser';
  help.textContent = 'Настроить помощник';
  const explanation = document.createElement('p');
  explanation.className = 'connection-next muted small';
  explanation.textContent =
    'Вход выполняется на livemaster.ru. Bamboo не получает пароль и cookies, а готовит поля и ZIP с фотографиями.';
  actions.append(help, explanation);

  const details = document.createElement('details');
  details.className = 'connection-disclosure';
  details.setAttribute('name', 'connection-setup');
  const summary = document.createElement('summary');
  const summaryTitle = document.createElement('span');
  summaryTitle.textContent = 'Как публиковать';
  const hint = document.createElement('span');
  hint.className = 'disclosure-hint';
  hint.textContent = 'Показать';
  summary.append(summaryTitle, hint);
  const body = document.createElement('div');
  body.className = 'connection-disclosure-body';
  const section = document.createElement('section');
  section.className = 'connection-section';
  const sectionHead = document.createElement('div');
  sectionHead.className = 'connection-section-head';
  const index = document.createElement('span');
  index.className = 'section-index';
  index.textContent = '1';
  const sectionCopy = document.createElement('div');
  const sectionTitle = document.createElement('h3');
  sectionTitle.textContent = 'Обычная авторизация в браузере';
  const sectionText = document.createElement('p');
  sectionText.textContent =
    'Создайте публикацию в Bamboo, откройте её пакет, скопируйте JSON и используйте закладку «Bamboo → заполнить Ярмарку». После проверки нажмите публикацию на самом сайте.';
  sectionCopy.append(sectionTitle, sectionText);
  sectionHead.append(index, sectionCopy);
  const links = document.createElement('div');
  links.className = 'quick-links';
  const open = document.createElement('a');
  open.className = 'button soft';
  open.href = 'https://www.livemaster.ru/';
  open.target = '_blank';
  open.rel = 'noopener';
  open.textContent = 'Открыть Ярмарку мастеров';
  const instructions = document.createElement('a');
  instructions.className = 'button quiet';
  instructions.href = '/static/help.html#livemaster-browser';
  instructions.textContent = 'Пошаговая инструкция';
  links.append(open, instructions);
  section.append(sectionHead, links);
  body.append(section);
  details.append(summary, body);

  card.append(header, actions, details);
  list.append(card);
})();
