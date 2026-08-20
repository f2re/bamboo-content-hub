(() => {
  const $ = (selector, root = document) => root.querySelector(selector);

  const replaceWithSelect = (card, fieldName, options, placeholder) => {
    const current = $(`[name="${fieldName}"]`, card);
    if (!current || current.tagName === 'SELECT' || !Array.isArray(options) || !options.length) return false;

    const select = document.createElement('select');
    select.name = fieldName;
    select.required = current.required;
    select.dataset.resourcePicker = fieldName;

    const empty = document.createElement('option');
    empty.value = '';
    empty.textContent = placeholder;
    select.append(empty);

    const currentValue = current.value || '';
    let currentFound = false;
    for (const item of options) {
      if (!item || item.value === undefined || item.value === null) continue;
      const option = document.createElement('option');
      option.value = String(item.value);
      option.textContent = String(item.label || item.value);
      if (option.value === currentValue) {
        option.selected = true;
        currentFound = true;
      }
      select.append(option);
    }
    if (currentValue && !currentFound) {
      const existing = document.createElement('option');
      existing.value = currentValue;
      existing.textContent = `Текущее значение: ${currentValue}`;
      existing.selected = true;
      select.append(existing);
    }
    current.replaceWith(select);
    return true;
  };

  const applyResourcePickers = (card, body) => {
    const details = body?.details || {};
    let changed = false;
    if (details.select_field && Array.isArray(details.options)) {
      changed = replaceWithSelect(
        card,
        details.select_field,
        details.options,
        body.message || 'Выберите вариант',
      ) || changed;
    }
    if (details.secondary_select_field && Array.isArray(details.secondary_options)) {
      changed = replaceWithSelect(
        card,
        details.secondary_select_field,
        details.secondary_options,
        'Без раздела',
      ) || changed;
    }
    return changed;
  };

  const check = async (button) => {
    const card = button.closest('[data-connection-card]');
    if (!card) return;
    const output = $('[data-health-result]', card);
    button.disabled = true;
    if (output) {
      output.textContent = 'Проверяю подключение и доступные варианты…';
      output.classList.remove('danger');
    }
    try {
      const response = await fetch(`/api/integrations/${button.dataset.health}/health`);
      let body = {};
      try {
        body = await response.json();
      } catch (_error) {
        body = {};
      }
      const pickerAdded = applyResourcePickers(card, body);
      if (output) {
        output.textContent = body.message || (body.ok ? 'Подключение работает' : 'Проверка не пройдена');
        output.classList.toggle('danger', !response.ok || (!body.ok && !pickerAdded));
        if (pickerAdded) {
          output.textContent += ' — выберите значение в списке и нажмите «Сохранить настройки».';
        }
      }
    } catch (_error) {
      if (output) {
        output.textContent = 'Не удалось связаться с Bamboo Content Hub';
        output.classList.add('danger');
      }
    } finally {
      button.disabled = false;
    }
  };

  document.addEventListener(
    'click',
    (event) => {
      const button = event.target.closest('[data-connection-card] [data-health]');
      if (!button) return;
      event.preventDefault();
      event.stopImmediatePropagation();
      check(button);
    },
    true,
  );
})();
