(() => {
  const form = document.querySelector('[data-publish-form]');
  if (!form) return;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const channelInputs = () => $$('input[name="channels"]', form);
  const mediaInputs = () => $$('input[name="media_ids"]:checked', form);
  const healthCache = new Map();
  let running = false;

  const panel = document.createElement('div');
  panel.className = 'notice publication-preflight';
  panel.innerHTML =
    '<strong>Готовность публикации</strong><p class="muted" data-preflight-summary>Выберите площадки — хаб проверит подключения и совместимость медиа до отправки.</p><button class="button small-button" type="button" data-preflight-check>Проверить выбранные</button>';
  const channels = $('.channels', form);
  channels?.insertAdjacentElement('afterend', panel);
  const summary = $('[data-preflight-summary]', panel);

  const statusNode = (input) => {
    const label = input.closest('label');
    if (!label) return null;
    let node = $('[data-channel-preflight]', label);
    if (!node) {
      node = document.createElement('span');
      node.dataset.channelPreflight = '';
      node.className = 'small muted';
      label.append(node);
    }
    return node;
  };

  const setStatus = (input, text, ok = null) => {
    const node = statusNode(input);
    if (!node) return;
    node.textContent = text ? ` · ${text}` : '';
    node.classList.toggle('danger', ok === false);
  };

  const selectedMediaTypes = () =>
    mediaInputs().map((input) => (input.closest('label')?.querySelector('video') ? 'video' : 'image'));

  const mediaErrors = (channel, capabilities = {}) => {
    const media = selectedMediaTypes();
    const errors = [];
    if (capabilities.max_media && media.length > capabilities.max_media) {
      errors.push(`не более ${capabilities.max_media} медиа`);
    }
    if (media.includes('image') && capabilities.images === false) errors.push('фото не поддерживаются');
    if (media.includes('video') && capabilities.videos === false) errors.push('видео не поддерживается');

    if (channel === 'instagram' && media.length === 0) errors.push('нужно выбрать фото или видео');
    if (channel === 'pinterest') {
      if (media.length !== 1 || media[0] !== 'image') errors.push('нужно выбрать ровно одно изображение');
    }
    if (channel === 'youtube') {
      if (media.length !== 1 || media[0] !== 'video') errors.push('нужно выбрать ровно одно видео');
    }
    if (channel === 'tiktok') {
      const images = media.filter((type) => type === 'image').length;
      const videos = media.filter((type) => type === 'video').length;
      if (!media.length) errors.push('нужно выбрать фото или видео');
      else if (images && videos) errors.push('нельзя смешивать фото и видео');
      else if (videos > 1) errors.push('можно выбрать только одно видео');
      else if (images > 35) errors.push('можно выбрать до 35 фото');
    }
    return [...new Set(errors)];
  };

  const fetchHealth = async (channel, force = false) => {
    if (!force && healthCache.has(channel)) return healthCache.get(channel);
    try {
      const response = await fetch(`/api/integrations/${channel}/health`);
      const body = await response.json();
      const needsTarget = Array.isArray(body?.details?.choices) && body.details.choices.length > 0;
      const result = {
        ok: response.ok && Boolean(body?.ok) && !needsTarget,
        needsTarget,
        message: body?.message || (body?.ok ? 'Подключение работает' : 'Проверка не пройдена'),
        capabilities: body?.capabilities || {},
      };
      healthCache.set(channel, result);
      return result;
    } catch (_error) {
      const result = {ok: false, needsTarget: false, message: 'Нет связи с хабом', capabilities: {}};
      healthCache.set(channel, result);
      return result;
    }
  };

  const checkInput = async (input, force = false) => {
    if (!input.checked) {
      setStatus(input, '');
      return {ok: true};
    }
    const channel = input.value;
    setStatus(input, 'проверяю…');
    const health = await fetchHealth(channel, force);
    if (health.needsTarget) {
      setStatus(input, 'завершите настройку', false);
      return {ok: false, message: `${channel}: выберите аккаунт/страницу в «Подключениях»`};
    }
    if (!health.ok) {
      setStatus(input, 'проблема подключения', false);
      return {ok: false, message: `${channel}: ${health.message}`};
    }
    const errors = mediaErrors(channel, health.capabilities);
    if (errors.length) {
      setStatus(input, errors[0], false);
      return {ok: false, message: `${channel}: ${errors.join(', ')}`};
    }
    const manual = health.capabilities?.automatic === false;
    setStatus(input, manual ? 'ручной экспорт' : 'готово', true);
    return {ok: true, manual};
  };

  const run = async (force = false) => {
    if (running) return false;
    running = true;
    const button = $('[data-preflight-check]', panel);
    if (button) button.disabled = true;
    if (summary) summary.textContent = 'Проверяю выбранные площадки…';
    const selected = channelInputs().filter((input) => input.checked);
    const results = [];
    try {
      for (const input of selected) results.push(await checkInput(input, force));
    } finally {
      running = false;
      if (button) button.disabled = false;
    }
    const failed = results.filter((result) => !result.ok);
    const manual = results.filter((result) => result.manual).length;
    if (summary) {
      if (failed.length) {
        summary.textContent = `Нужно исправить: ${failed.map((item) => item.message).join('; ')}. Настройки площадок находятся в разделе «Подключения».`;
        summary.classList.add('danger');
      } else {
        summary.textContent = manual
          ? 'Все выбранные варианты готовы. Для ручной площадки хаб подготовит карточку, остальные отправит автоматически.'
          : 'Все выбранные площадки и медиа готовы к публикации.';
        summary.classList.remove('danger');
      }
    }
    return failed.length === 0;
  };

  panel.addEventListener('click', (event) => {
    if (event.target.closest('[data-preflight-check]')) run(true);
  });

  form.addEventListener('change', (event) => {
    if (event.target.matches('input[name="channels"]')) {
      checkInput(event.target, true);
      return;
    }
    if (event.target.matches('input[name="media_ids"]')) {
      for (const input of channelInputs().filter((item) => item.checked)) {
        const cached = healthCache.get(input.value);
        if (!cached?.ok) continue;
        const errors = mediaErrors(input.value, cached.capabilities);
        if (errors.length) setStatus(input, errors[0], false);
        else setStatus(input, cached.capabilities?.automatic === false ? 'ручной экспорт' : 'готово', true);
      }
    }
  });

  form.addEventListener(
    'submit',
    async (event) => {
      if (form.dataset.preflightPassed === 'true') {
        delete form.dataset.preflightPassed;
        return;
      }
      if (event.submitter?.value === 'draft') return;
      event.preventDefault();
      event.stopImmediatePropagation();
      const ok = await run(true);
      if (!ok) return;
      form.dataset.preflightPassed = 'true';
      form.requestSubmit(event.submitter || undefined);
    },
    true,
  );

  for (const input of channelInputs().filter((item) => item.checked)) checkInput(input);
})();
