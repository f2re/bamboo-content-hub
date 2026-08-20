const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const csrf = () => $('meta[name="csrf-token"]')?.content || '';

const api = async (url, options = {}) => {
  const headers = new Headers(options.headers || {});
  const token = csrf();
  if (token) headers.set('x-csrf-token', token);
  return fetch(url, {...options, headers});
};

const responseBody = async (response) => {
  try {
    return await response.json();
  } catch (_error) {
    return {};
  }
};

const errorMessage = (body, fallback = 'Не удалось выполнить операцию') => {
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.message === 'string') return body.message;
  return fallback;
};

const copyText = async (source) => {
  const text = 'value' in source ? source.value : source.textContent || '';
  if (navigator.clipboard?.writeText && window.isSecureContext) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const active = document.activeElement;
  let target = source;
  let temporary = false;
  if (!(source instanceof HTMLTextAreaElement) && !(source instanceof HTMLInputElement)) {
    target = document.createElement('textarea');
    target.value = text;
    target.setAttribute('readonly', '');
    target.style.position = 'fixed';
    target.style.opacity = '0';
    document.body.append(target);
    temporary = true;
  }
  target.focus();
  target.select();
  if (target.setSelectionRange) target.setSelectionRange(0, text.length);
  const copied = document.execCommand('copy');
  if (temporary) target.remove();
  if (active?.focus) active.focus();
  if (!copied) throw new Error('copy failed');
};

const healthText = (body) => {
  const details = body?.details || {};
  const account = details.nickname || details.title || details.username || '';
  const suffix = account ? ` · ${account}` : '';
  return `${body?.message || (body?.ok ? 'Подключение работает' : 'Проверка не пройдена')}${suffix}`;
};

const renderConnectionChoices = (scope, body) => {
  const host = $('[data-choice-list]', scope);
  if (!host) return;
  host.innerHTML = '';
  const choices = body?.details?.choices;
  if (!Array.isArray(choices) || !choices.length) return;

  const title = document.createElement('p');
  title.className = 'field-help';
  title.textContent = 'Выберите вариант — ID подставятся и сохранятся автоматически:';
  host.append(title);

  for (const choice of choices) {
    if (!choice || typeof choice !== 'object' || typeof choice.values !== 'object') continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'choice-button';
    button.textContent = choice.label || 'Выбрать';
    button.addEventListener('click', () => {
      const form = $('.target-form', scope) || $('[data-integration-form]', scope);
      if (!form) return;
      for (const [name, value] of Object.entries(choice.values || {})) {
        const input = $(`[name="${name}"]`, form);
        if (input) input.value = value ?? '';
      }
      const message = $('[data-config-result]', form);
      if (message) message.textContent = 'Выбрано. Сохраняю…';
      form.requestSubmit();
    });
    host.append(button);
  }
};

const runHealthCheck = async (button) => {
  const channel = button.dataset.health;
  const scope = button.closest('[data-connection-card], [data-channel-settings]') || document;
  const output = $('[data-health-result]', scope);
  if (output) output.textContent = 'Проверяю…';
  button.disabled = true;
  try {
    const response = await api(`/api/integrations/${channel}/health`);
    const body = await responseBody(response);
    if (output) {
      output.textContent = response.ok ? healthText(body) : errorMessage(body);
      output.classList.toggle('danger', !response.ok || !body.ok);
    }
    renderConnectionChoices(scope, body);
    return body;
  } catch (_error) {
    if (output) {
      output.textContent = 'Нет связи с Bamboo Content Hub';
      output.classList.add('danger');
    }
    return {ok: false};
  } finally {
    button.disabled = false;
  }
};

const privacyLabels = {
  PUBLIC_TO_EVERYONE: 'Для всех',
  MUTUAL_FOLLOW_FRIENDS: 'Друзья',
  FOLLOWER_OF_CREATOR: 'Подписчики',
  SELF_ONLY: 'Только я',
};

const updateTikTokDisclosure = (panel) => {
  const commercial = $('[data-tiktok-commercial]', panel);
  const disclosure = $('[data-tiktok-disclosure]', panel);
  const ownBrand = $('[data-tiktok-own-brand]', panel);
  const branded = $('[data-tiktok-branded]', panel);
  const privacy = $('[data-tiktok-privacy]', panel);
  const consentText = $('[data-tiktok-consent-text]', panel);
  if (!commercial || !disclosure) return;

  disclosure.hidden = !commercial.checked;
  if (!commercial.checked) {
    if (ownBrand) ownBrand.checked = false;
    if (branded) branded.checked = false;
  }

  const selfOnly = [...(privacy?.options || [])].find((option) => option.value === 'SELF_ONLY');
  if (selfOnly) selfOnly.disabled = Boolean(commercial.checked && branded?.checked);
  if (privacy?.value === 'SELF_ONLY' && branded?.checked) privacy.value = '';

  if (consentText) {
    if (commercial.checked && branded?.checked) {
      consentText.textContent =
        'Разрешаю отправку в TikTok и принимаю правила брендированного контента и использования музыки.';
    } else if (commercial.checked && ownBrand?.checked) {
      consentText.textContent =
        'Разрешаю отправку в TikTok и принимаю подтверждение использования музыки.';
    } else {
      consentText.textContent =
        'Разрешаю отправить выбранные материалы и текст в подключённый аккаунт TikTok.';
    }
  }
};

const applyTikTokCreator = (panel, body) => {
  const checked = $('[data-tiktok-creator-checked]', panel);
  const account = $('[data-tiktok-account]', panel);
  const privacy = $('[data-tiktok-privacy]', panel);
  const details = body?.details || {};
  if (!body?.ok) {
    if (checked) checked.value = 'false';
    if (account) {
      account.textContent = body?.message || 'Не удалось получить сведения об аккаунте TikTok';
      account.classList.add('danger');
    }
    if (privacy) privacy.innerHTML = '<option value="">Подключение не проверено</option>';
    return;
  }

  if (checked) checked.value = 'true';
  if (account) {
    const duration = details.max_video_post_duration_sec
      ? ` · видео до ${details.max_video_post_duration_sec} с`
      : '';
    account.textContent = `${details.nickname || details.username || 'TikTok аккаунт'}${duration}`;
    account.classList.remove('danger');
  }
  if (privacy) {
    privacy.innerHTML = '<option value="">Выберите видимость</option>';
    for (const value of details.privacy_level_options || []) {
      const option = document.createElement('option');
      option.value = value;
      option.textContent = privacyLabels[value] || value;
      privacy.append(option);
    }
  }
  for (const [name, disabled] of [
    ['comment', details.comment_disabled],
    ['duet', details.duet_disabled],
    ['stitch', details.stitch_disabled],
  ]) {
    const control = $(`[data-tiktok-control="${name}"]`, panel);
    if (!control) continue;
    control.disabled = Boolean(disabled);
    if (disabled) control.checked = true;
  }
  updateTikTokDisclosure(panel);
};

const loadTikTokCreator = async (panel) => {
  const button = $('[data-load-tiktok]', panel);
  const account = $('[data-tiktok-account]', panel);
  if (account) account.textContent = 'Получаю актуальные настройки TikTok…';
  if (button) button.disabled = true;
  try {
    const response = await api('/api/integrations/tiktok/health');
    const body = await responseBody(response);
    applyTikTokCreator(panel, response.ok ? body : {ok: false, message: errorMessage(body)});
  } catch (_error) {
    applyTikTokCreator(panel, {ok: false, message: 'Нет связи с Bamboo Content Hub'});
  } finally {
    if (button) button.disabled = false;
  }
};

const syncChannelPanels = () => {
  for (const panel of $$('[data-channel-settings]')) {
    const channel = panel.dataset.channelSettings;
    const toggle = $(`[data-channel-toggle="${channel}"]`);
    panel.hidden = !toggle?.checked;
    if (channel === 'tiktok' && toggle?.checked && panel.dataset.loaded !== 'true') {
      panel.dataset.loaded = 'true';
      loadTikTokCreator(panel);
    }
  }
};

const validatePublishForm = (form) => {
  const selected = (channel) => $(`[data-channel-toggle="${channel}"]`, form)?.checked;
  if (selected('tiktok')) {
    const panel = $('[data-channel-settings="tiktok"]', form);
    if ($('[data-tiktok-creator-checked]', panel)?.value !== 'true') {
      alert('Сначала обновите сведения о подключённом TikTok аккаунте.');
      return false;
    }
    const privacy = $('[data-tiktok-privacy]', panel)?.value;
    if (!privacy) {
      alert('Выберите видимость публикации TikTok.');
      return false;
    }
    const commercial = $('[data-tiktok-commercial]', panel)?.checked;
    const ownBrand = $('[data-tiktok-own-brand]', panel)?.checked;
    const branded = $('[data-tiktok-branded]', panel)?.checked;
    if (commercial && !ownBrand && !branded) {
      alert('Укажите, продвигает публикация свой бренд, сторонний бренд или оба.');
      return false;
    }
    if (branded && privacy === 'SELF_ONLY') {
      alert('Платное партнёрство TikTok нельзя публиковать с видимостью «Только я».');
      return false;
    }
    if (!$('[data-tiktok-consent]', panel)?.checked) {
      alert('Подтвердите отправку материалов в TikTok.');
      return false;
    }
  }
  if (selected('youtube')) {
    const panel = $('[data-channel-settings="youtube"]', form);
    if (!$('input[name="youtube_title"]', panel)?.value.trim()) {
      alert('Укажите заголовок YouTube.');
      return false;
    }
    if (!$('[data-youtube-privacy]', panel)?.value) {
      alert('Выберите видимость YouTube.');
      return false;
    }
  }
  return true;
};

const renderAiPreview = (body) => {
  const output = $('#ai-result');
  if (!output) return;
  const pack = body?.pack || {};
  const product = pack.product || {};
  const content = pack.content || {};
  const dimensions = product.dimensions || {};
  const rows = [
    ['Название', product.name],
    ['Тип', product.product_type],
    ['Коллекция', product.collection],
    ['Цена', product.price?.amount ? `${product.price.amount} ${product.price.currency || 'RUB'}` : null],
    ['Материалы', (product.materials || []).join(', ')],
    ['Высота', dimensions.height_mm ? `${dimensions.height_mm} мм` : null],
    ['Диаметр', dimensions.diameter_mm ? `${dimensions.diameter_mm} мм` : null],
    ['Объём', dimensions.volume_ml ? `${dimensions.volume_ml} мл` : null],
    ['Описание', content.full_description || content.short_description],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '');

  output.innerHTML = '';
  const title = document.createElement('h4');
  title.textContent = 'Что предлагает ИИ';
  output.append(title);
  const list = document.createElement('dl');
  list.className = 'ai-preview-list';
  for (const [label, value] of rows) {
    const dt = document.createElement('dt');
    dt.textContent = label;
    const dd = document.createElement('dd');
    dd.textContent = String(value);
    list.append(dt, dd);
  }
  output.append(list);

  const confirmations = body?.needs_confirmation || [];
  if (confirmations.length) {
    const box = document.createElement('div');
    box.className = 'ai-warning';
    const heading = document.createElement('strong');
    heading.textContent = 'Нужно уточнить перед использованием';
    box.append(heading);
    const ul = document.createElement('ul');
    for (const item of confirmations) {
      const li = document.createElement('li');
      li.textContent = item.question || item.path;
      ul.append(li);
    }
    box.append(ul);
    output.append(box);
  }

  const assumptions = body?.assumptions || [];
  if (assumptions.length) {
    const details = document.createElement('details');
    const summary = document.createElement('summary');
    summary.textContent = `Предположения ИИ: ${assumptions.length}`;
    details.append(summary);
    const ul = document.createElement('ul');
    for (const item of assumptions) {
      const li = document.createElement('li');
      li.textContent = `${item.path}: ${item.basis || 'без подтверждения'}`;
      ul.append(li);
    }
    details.append(ul);
    output.append(details);
  }
};

const uploadWithProgress = (form) => {
  const input = $('[data-upload-input]', form);
  if (!input?.files?.length) return false;
  const status = $('[data-upload-status]', form);
  const progress = $('[data-upload-progress]', form);
  const message = $('[data-upload-message]', form);
  const button = $('button[type="submit"]', form);
  const data = new FormData(form);
  const xhr = new XMLHttpRequest();
  xhr.open('POST', form.action);
  const token = csrf();
  if (token) xhr.setRequestHeader('x-csrf-token', token);
  xhr.setRequestHeader('Accept', 'text/html,application/json');
  if (status) status.hidden = false;
  if (button) button.disabled = true;
  if (message) message.textContent = `Загрузка: ${input.files.length} файл(ов)…`;
  xhr.upload.addEventListener('progress', (event) => {
    if (!event.lengthComputable) return;
    const percent = Math.round((event.loaded / event.total) * 100);
    if (progress) progress.style.width = `${percent}%`;
    if (message) message.textContent = `Загружено ${percent}% · после загрузки медиа будет оптимизировано`;
  });
  xhr.addEventListener('load', () => {
    if (xhr.status >= 200 && xhr.status < 400) {
      if (message) message.textContent = 'Готово. Обновляю медиатеку…';
      location.reload();
      return;
    }
    let text = 'Не удалось загрузить файл';
    try {
      text = errorMessage(JSON.parse(xhr.responseText), text);
    } catch (_error) {
      // keep the human fallback
    }
    if (message) message.textContent = text;
    if (status) status.classList.add('danger');
    if (button) button.disabled = false;
  });
  xhr.addEventListener('error', () => {
    if (message) message.textContent = 'Соединение прервано. Файл можно загрузить повторно.';
    if (status) status.classList.add('danger');
    if (button) button.disabled = false;
  });
  xhr.send(data);
  return true;
};

const persistMediaOrder = async (grid) => {
  const ids = $$('[data-media-id]', grid).map((item) => item.dataset.mediaId);
  if (!ids.length) return;
  const productId = grid.dataset.productId;
  const response = await api(`/api/products/${productId}/media/order`, {
    method: 'POST',
    headers: {'content-type': 'application/json'},
    body: JSON.stringify({ids}),
  });
  if (!response.ok) {
    alert(errorMessage(await responseBody(response), 'Не удалось сохранить порядок медиа'));
    location.reload();
  }
};

const initMediaDragDrop = () => {
  for (const grid of $$('[data-media-grid]')) {
    let dragged = null;
    grid.addEventListener('dragstart', (event) => {
      dragged = event.target.closest('[data-media-id]');
      if (dragged) dragged.classList.add('dragging');
    });
    grid.addEventListener('dragover', (event) => {
      event.preventDefault();
      if (!dragged) return;
      const target = event.target.closest('[data-media-id]');
      if (!target || target === dragged) return;
      const box = target.getBoundingClientRect();
      const after = event.clientX > box.left + box.width / 2;
      grid.insertBefore(dragged, after ? target.nextSibling : target);
    });
    grid.addEventListener('dragend', async () => {
      if (dragged) dragged.classList.remove('dragging');
      dragged = null;
      const items = $$('[data-media-id]', grid);
      items.forEach((item, index) => {
        const badge = $('.media-index', item);
        if (badge) badge.textContent = index === 0 ? 'Обложка' : String(index + 1);
      });
      await persistMediaOrder(grid);
    });
  }
};

document.addEventListener('submit', async (event) => {
  const integrationForm = event.target.closest('[data-integration-form]');
  if (integrationForm) {
    event.preventDefault();
    const provider = integrationForm.dataset.provider;
    const output = $('[data-config-result]', integrationForm);
    const payload = {};
    for (const field of integrationForm.elements) {
      if (!field.name || field.disabled) continue;
      if (field.type === 'checkbox') {
        payload[field.name] = field.checked;
      } else if (field.dataset.secretField !== undefined && !field.value.trim()) {
        continue;
      } else {
        payload[field.name] = field.value;
      }
    }
    if (output) output.textContent = 'Сохраняю…';
    try {
      const response = await api(`/api/integrations/${provider}/config`, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify(payload),
      });
      const body = await responseBody(response);
      if (!response.ok) throw new Error(errorMessage(body));
      if (output) output.textContent = 'Сохранено';
      setTimeout(() => location.reload(), 450);
    } catch (error) {
      if (output) {
        output.textContent = error.message || 'Не удалось сохранить настройки';
        output.classList.add('danger');
      }
    }
    return;
  }

  const uploadForm = event.target.closest('[data-upload-form]');
  if (uploadForm) {
    event.preventDefault();
    uploadWithProgress(uploadForm);
    return;
  }

  const publishForm = event.target.closest('[data-publish-form]');
  if (publishForm && !validatePublishForm(publishForm)) event.preventDefault();
});

document.addEventListener('change', (event) => {
  if (event.target.matches('[data-channel-toggle]')) syncChannelPanels();
  if (
    event.target.matches(
      '[data-tiktok-commercial], [data-tiktok-own-brand], [data-tiktok-branded], [data-tiktok-privacy]',
    )
  ) {
    const panel = event.target.closest('[data-channel-settings="tiktok"]');
    if (panel) updateTikTokDisclosure(panel);
  }
});

document.addEventListener('click', async (event) => {
  const copy = event.target.closest('[data-copy]');
  if (copy) {
    const source = $(copy.dataset.copy);
    if (!source) return;
    const original = copy.textContent;
    copy.disabled = true;
    try {
      await copyText(source);
      copy.textContent = 'Скопировано';
    } catch (_error) {
      copy.textContent = 'Не удалось скопировать';
    } finally {
      setTimeout(() => {
        copy.textContent = original;
        copy.disabled = false;
      }, 1400);
    }
    return;
  }

  const reloadPrompt = event.target.closest('[data-reload-prompt]');
  if (reloadPrompt) {
    reloadPrompt.disabled = true;
    reloadPrompt.textContent = 'Обновляю…';
    location.reload();
    return;
  }

  const preview = event.target.closest('[data-preview]');
  if (preview) {
    preview.disabled = true;
    const response = await api(`/api/products/${preview.dataset.preview}/ai/preview`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({text: $('#ai-answer')?.value || ''}),
    });
    const body = await responseBody(response);
    if (response.ok) renderAiPreview(body);
    else if ($('#ai-result')) $('#ai-result').textContent = errorMessage(body);
    preview.disabled = false;
    return;
  }

  const importer = event.target.closest('[data-import]');
  if (importer) {
    const response = await api(`/api/products/${importer.dataset.import}/ai/import`, {
      method: 'POST',
      headers: {'content-type': 'application/json'},
      body: JSON.stringify({text: $('#ai-answer')?.value || ''}),
    });
    const body = await responseBody(response);
    if (response.ok) location.href = body.redirect;
    else if ($('#ai-result')) $('#ai-result').textContent = errorMessage(body);
    return;
  }

  const deleteMedia = event.target.closest('[data-delete-media]');
  if (deleteMedia) {
    const grid = deleteMedia.closest('[data-media-grid]');
    if (!grid || !confirm('Удалить этот файл из изделия?')) return;
    deleteMedia.disabled = true;
    const response = await api(
      `/api/products/${grid.dataset.productId}/media/${deleteMedia.dataset.deleteMedia}`,
      {method: 'DELETE'},
    );
    if (response.ok) location.reload();
    else {
      alert(errorMessage(await responseBody(response), 'Не удалось удалить файл'));
      deleteMedia.disabled = false;
    }
    return;
  }

  const publish = event.target.closest('[data-publish]');
  if (publish) {
    const response = await api(`/api/publications/${publish.dataset.publish}/publish`, {
      method: 'POST',
    });
    if (response.ok) location.reload();
    else alert(errorMessage(await responseBody(response), 'Не удалось запустить публикацию'));
    return;
  }

  const health = event.target.closest('[data-health]');
  if (health) {
    await runHealthCheck(health);
    return;
  }

  const tiktok = event.target.closest('[data-load-tiktok]');
  if (tiktok) {
    const panel = tiktok.closest('[data-channel-settings="tiktok"]');
    if (panel) await loadTikTokCreator(panel);
    return;
  }

  const disconnect = event.target.closest('[data-disconnect]');
  if (disconnect && confirm('Отключить интеграцию? История публикаций сохранится.')) {
    const response = await api(`/api/integrations/${disconnect.dataset.disconnect}`, {
      method: 'DELETE',
    });
    if (response.ok) location.reload();
    else alert(errorMessage(await responseBody(response), 'Не удалось отключить интеграцию'));
  }
});

for (const zone of $$('.drop-zone')) {
  for (const eventName of ['dragenter', 'dragover']) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.add('drop-active');
    });
  }
  for (const eventName of ['dragleave', 'drop']) {
    zone.addEventListener(eventName, (event) => {
      event.preventDefault();
      zone.classList.remove('drop-active');
    });
  }
  zone.addEventListener('drop', (event) => {
    const input = $('[data-upload-input]', zone);
    if (input && event.dataTransfer?.files?.length) input.files = event.dataTransfer.files;
  });
}

syncChannelPanels();
for (const panel of $$('[data-channel-settings="tiktok"]')) updateTikTokDisclosure(panel);
initMediaDragDrop();
