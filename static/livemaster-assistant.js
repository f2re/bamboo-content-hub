(() => {
  function bambooLivemasterFill() {
    const normalize = (value) =>
      String(value || '')
        .toLocaleLowerCase('ru-RU')
        .replace(/ё/g, 'е')
        .replace(/\s+/g, ' ')
        .trim();

    const fieldDescription = (element) => {
      const parts = [
        element.name,
        element.id,
        element.getAttribute('placeholder'),
        element.getAttribute('aria-label'),
        element.getAttribute('data-testid'),
      ];
      if (element.labels) parts.push(...[...element.labels].map((label) => label.textContent));
      const closestLabel = element.closest('label');
      if (closestLabel) parts.push(closestLabel.textContent);
      const labelledBy = element.getAttribute('aria-labelledby');
      if (labelledBy) {
        for (const id of labelledBy.split(/\s+/)) parts.push(document.getElementById(id)?.textContent);
      }
      return normalize(parts.filter(Boolean).join(' '));
    };

    const candidates = [...document.querySelectorAll('input, textarea, select, [contenteditable="true"]')]
      .filter((element) => {
        if (element.disabled || element.readOnly) return false;
        if (element instanceof HTMLInputElement) {
          return !['hidden', 'file', 'submit', 'button', 'reset', 'checkbox', 'radio'].includes(
            element.type,
          );
        }
        return true;
      })
      .map((element) => ({element, description: fieldDescription(element)}));

    const nativeSet = (element, value) => {
      const text = String(value ?? '').trim();
      if (!text) return false;
      if (element.isContentEditable) {
        element.focus();
        element.textContent = text;
      } else {
        const prototype =
          element instanceof HTMLTextAreaElement
            ? HTMLTextAreaElement.prototype
            : element instanceof HTMLSelectElement
              ? HTMLSelectElement.prototype
              : HTMLInputElement.prototype;
        const setter = Object.getOwnPropertyDescriptor(prototype, 'value')?.set;
        if (setter) setter.call(element, text);
        else element.value = text;
      }
      for (const type of ['input', 'change', 'blur']) {
        element.dispatchEvent(new Event(type, {bubbles: true}));
      }
      return true;
    };

    const bestField = (tokens, excludes, used) => {
      let best = null;
      let bestScore = 0;
      for (const candidate of candidates) {
        if (used.has(candidate.element)) continue;
        if (excludes.some((token) => candidate.description.includes(normalize(token)))) continue;
        let score = 0;
        for (const token of tokens) {
          const normalizedToken = normalize(token);
          if (!normalizedToken) continue;
          if (candidate.description === normalizedToken) score += 12;
          else if (candidate.description.includes(normalizedToken)) score += 5;
        }
        if (score > bestScore) {
          best = candidate.element;
          bestScore = score;
        }
      }
      return bestScore >= 5 ? best : null;
    };

    const report = (filled, missing, skipped) => {
      document.getElementById('bamboo-livemaster-report')?.remove();
      const panel = document.createElement('section');
      panel.id = 'bamboo-livemaster-report';
      Object.assign(panel.style, {
        position: 'fixed',
        zIndex: '2147483647',
        right: '18px',
        bottom: '18px',
        width: 'min(390px, calc(100vw - 36px))',
        maxHeight: '70vh',
        overflow: 'auto',
        padding: '18px',
        borderRadius: '16px',
        background: '#ffffff',
        color: '#1d1d1f',
        boxShadow: '0 18px 60px rgba(0,0,0,.24)',
        border: '1px solid #d8d8dc',
        font: '14px/1.45 -apple-system,BlinkMacSystemFont,Segoe UI,sans-serif',
      });
      const heading = document.createElement('strong');
      heading.textContent = 'Bamboo Pottery · заполнение';
      heading.style.fontSize = '16px';
      const text = document.createElement('p');
      text.textContent = `Заполнено: ${filled.length}. Не найдено: ${missing.length}. Не перезаписано: ${skipped.length}.`;
      const details = document.createElement('p');
      details.style.color = '#6e6e73';
      details.textContent = missing.length
        ? `Проверьте вручную: ${missing.join(', ')}. Фото загрузите из ZIP-пакета Bamboo.`
        : 'Проверьте поля и загрузите фото из ZIP-пакета Bamboo.';
      const close = document.createElement('button');
      close.type = 'button';
      close.textContent = 'Закрыть';
      Object.assign(close.style, {
        border: '0',
        borderRadius: '10px',
        padding: '9px 14px',
        background: '#0071e3',
        color: '#fff',
        cursor: 'pointer',
      });
      close.addEventListener('click', () => panel.remove());
      panel.append(heading, text, details, close);
      document.body.append(panel);
    };

    const readPayload = async () => {
      let raw = '';
      try {
        raw = await navigator.clipboard.readText();
      } catch (_error) {
        raw = '';
      }
      if (!raw || !raw.includes('bamboo-browser-fill')) {
        raw = window.prompt('Вставьте JSON из блока «Данные для помощника» в Bamboo:', '') || '';
      }
      if (!raw.trim()) return null;
      try {
        return JSON.parse(raw);
      } catch (_error) {
        window.alert('Bamboo: в буфере нет корректного JSON-пакета. Скопируйте его заново.');
        return null;
      }
    };

    const run = async () => {
      const payload = await readPayload();
      if (!payload) return;
      if (payload.schema !== 'bamboo-browser-fill/1' || payload.platform !== 'livemaster') {
        window.alert('Bamboo: этот пакет не предназначен для Ярмарки мастеров.');
        return;
      }

      const mappings = [
        {key: 'title', label: 'название', tokens: ['название', 'наименование', 'заголовок'], excludes: ['seo', 'кратк', 'коротк']},
        {key: 'short_description', label: 'краткое описание', tokens: ['краткое описание', 'короткое описание'], excludes: []},
        {key: 'description', label: 'описание', tokens: ['описание товара', 'описание работы', 'описание'], excludes: ['кратк', 'коротк', 'seo']},
        {key: 'price', label: 'цена', tokens: ['цена', 'стоимость'], excludes: ['доставка']},
        {key: 'materials', label: 'материалы', tokens: ['материалы', 'материал'], excludes: []},
        {key: 'dimensions', label: 'размеры', tokens: ['размеры', 'размер', 'габариты'], excludes: []},
        {key: 'keywords', label: 'ключевые слова', tokens: ['ключевые слова', 'теги', 'метки'], excludes: []},
        {key: 'availability', label: 'наличие', tokens: ['наличие', 'статус товара'], excludes: []},
      ];
      const used = new Set();
      const filled = [];
      const missing = [];
      const skipped = [];

      for (const mapping of mappings) {
        const value = payload[mapping.key];
        if (value === null || value === undefined || String(value).trim() === '') continue;
        const field = bestField(mapping.tokens, mapping.excludes, used);
        if (!field) {
          missing.push(mapping.label);
          continue;
        }
        used.add(field);
        const current = normalize(field.isContentEditable ? field.textContent : field.value);
        if (current && current !== normalize(value)) {
          skipped.push(mapping.label);
          continue;
        }
        if (nativeSet(field, value)) filled.push(mapping.label);
        else missing.push(mapping.label);
      }
      report(filled, missing, skipped);
    };

    run();
  }

  const bookmarklet = `javascript:(${bambooLivemasterFill.toString()})()`;

  for (const link of document.querySelectorAll('[data-livemaster-bookmarklet]')) {
    link.setAttribute('href', bookmarklet);
    link.addEventListener('click', async (event) => {
      event.preventDefault();
      const output = document.querySelector('[data-bookmarklet-result]');
      try {
        await navigator.clipboard.writeText(bookmarklet);
        if (output) output.textContent = 'Код помощника скопирован. Создайте закладку и вставьте код в поле адреса.';
      } catch (_error) {
        if (output) output.textContent = 'Перетащите кнопку на панель закладок — копирование браузером запрещено.';
      }
    });
  }
})();
