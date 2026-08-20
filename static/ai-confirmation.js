(() => {
  let reviewedPack = null;

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
  const csrf = () => $('meta[name="csrf-token"]')?.content || '';

  const requestJson = async (url, options = {}) => {
    const headers = new Headers(options.headers || {});
    const token = csrf();
    if (token) headers.set('x-csrf-token', token);
    const response = await fetch(url, {...options, headers});
    let body = {};
    try {
      body = await response.json();
    } catch (_error) {
      body = {};
    }
    if (!response.ok) {
      const detail = typeof body?.detail === 'string' ? body.detail : 'Не удалось проверить ответ ИИ';
      throw new Error(detail);
    }
    return body;
  };

  const valueText = (value) => {
    if (value === true) return 'да';
    if (value === false) return 'нет';
    if (Array.isArray(value)) return value.join(', ');
    if (value === null || value === undefined || value === '') return 'не указано';
    return String(value);
  };

  const renderPreview = (body) => {
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
      ['Описание', content.full_description || content.short_description],
    ].filter(([, value]) => value !== null && value !== undefined && value !== '');

    output.innerHTML = '';
    const heading = document.createElement('h4');
    heading.textContent = 'Что будет добавлено';
    output.append(heading);

    if (rows.length) {
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
    }

    const confirmations = pack.needs_confirmation || [];
    const signed = confirmations.filter((item) => item.proof && item.value !== null && item.value !== undefined);
    const questions = confirmations.filter((item) => !item.proof || item.value === null || item.value === undefined);

    if (signed.length) {
      const box = document.createElement('div');
      box.className = 'ai-warning ai-confirm-list';
      const title = document.createElement('strong');
      title.textContent = 'Подтвердите факты, которые нельзя определять по фотографии';
      box.append(title);
      const explanation = document.createElement('p');
      explanation.className = 'muted';
      explanation.textContent = 'Отметьте только то, что вы знаете наверняка. Неотмеченные значения не попадут в карточку.';
      box.append(explanation);
      for (const item of signed) {
        const label = document.createElement('label');
        label.className = 'check-row ai-confirm-row';
        const input = document.createElement('input');
        input.type = 'checkbox';
        input.dataset.aiConfirmPath = item.path;
        const text = document.createElement('span');
        text.textContent = item.question || `${item.path}: ${valueText(item.value)}`;
        label.append(input, text);
        box.append(label);
      }
      output.append(box);
    }

    if (questions.length) {
      const box = document.createElement('div');
      box.className = 'ai-question-list';
      const title = document.createElement('strong');
      title.textContent = 'Что стоит уточнить';
      box.append(title);
      const ul = document.createElement('ul');
      for (const item of questions) {
        const li = document.createElement('li');
        li.textContent = item.question || item.path;
        ul.append(li);
      }
      box.append(ul);
      output.append(box);
    }

    const assumptions = pack.assumptions || [];
    if (assumptions.length) {
      const details = document.createElement('details');
      const summary = document.createElement('summary');
      summary.textContent = `Предположения ИИ: ${assumptions.length}`;
      details.append(summary);
      const ul = document.createElement('ul');
      for (const item of assumptions) {
        const li = document.createElement('li');
        li.textContent = `${item.path}: ${item.basis || valueText(item.value)}`;
        ul.append(li);
      }
      details.append(ul);
      output.append(details);
    }

    const ready = document.createElement('p');
    ready.className = 'muted ai-ready-message';
    ready.textContent = signed.length
      ? 'После выбора подтверждений нажмите «Применить подтверждённое».'
      : 'Ответ проверен. Можно импортировать безопасные данные.';
    output.append(ready);
  };

  const preview = async (button) => {
    button.disabled = true;
    reviewedPack = null;
    const output = $('#ai-result');
    if (output) output.textContent = 'Проверяю ответ…';
    try {
      const body = await requestJson(`/api/products/${button.dataset.preview}/ai/preview`, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({text: $('#ai-answer')?.value || ''}),
      });
      reviewedPack = body.pack;
      renderPreview(body);
    } catch (error) {
      if (output) output.textContent = error.message || 'Не удалось проверить ответ';
    } finally {
      button.disabled = false;
    }
  };

  const importPack = async (button) => {
    button.disabled = true;
    const output = $('#ai-result');
    try {
      let text = $('#ai-answer')?.value || '';
      if (reviewedPack) {
        const pack = JSON.parse(JSON.stringify(reviewedPack));
        const confirmed = new Set(
          $$('[data-ai-confirm-path]:checked').map((input) => input.dataset.aiConfirmPath),
        );
        for (const item of pack.needs_confirmation || []) {
          if (item.proof) item.confirmed = confirmed.has(item.path);
        }
        text = JSON.stringify(pack);
      }
      const body = await requestJson(`/api/products/${button.dataset.import}/ai/import`, {
        method: 'POST',
        headers: {'content-type': 'application/json'},
        body: JSON.stringify({text}),
      });
      location.href = body.redirect;
    } catch (error) {
      if (output) output.textContent = error.message || 'Не удалось импортировать ответ';
      button.disabled = false;
    }
  };

  document.addEventListener(
    'click',
    (event) => {
      const previewButton = event.target.closest('[data-preview]');
      if (previewButton) {
        event.preventDefault();
        event.stopImmediatePropagation();
        preview(previewButton);
        return;
      }
      const importButton = event.target.closest('[data-import]');
      if (importButton) {
        event.preventDefault();
        event.stopImmediatePropagation();
        importPack(importButton);
      }
    },
    true,
  );

  $('#ai-answer')?.addEventListener('input', () => {
    reviewedPack = null;
    const output = $('#ai-result');
    if (output) output.innerHTML = '';
  });
})();
