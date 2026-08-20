(() => {
  const labels = {
    tiktok: 'TikTok',
    youtube: 'YouTube',
  };

  const hiddenInput = (name, value, attributes = {}) => {
    const input = document.createElement('input');
    input.type = 'hidden';
    if (name) input.name = name;
    input.value = value ?? '';
    for (const [key, attributeValue] of Object.entries(attributes)) {
      if (attributeValue === true) input.setAttribute(key, '');
      else input.setAttribute(key, String(attributeValue));
    }
    return input;
  };

  const preserveManualFormContract = (panel, channel, values) => {
    const fields = document.createElement('div');
    fields.hidden = true;
    fields.dataset.manualCompatibility = '';

    if (channel === 'tiktok') {
      fields.append(
        hiddenInput('tiktok_title', values.title),
        hiddenInput('tiktok_caption', values.caption),
        hiddenInput('tiktok_creator_checked', 'true', {'data-tiktok-creator-checked': true}),
        hiddenInput('tiktok_privacy_level', 'MANUAL', {'data-tiktok-privacy': true}),
      );
      const consent = document.createElement('input');
      consent.type = 'checkbox';
      consent.checked = true;
      consent.dataset.tiktokConsent = '';
      fields.append(consent);
    }

    if (channel === 'youtube') {
      fields.append(
        hiddenInput('youtube_title', values.title),
        hiddenInput('youtube_description', values.description),
      );
    }

    panel.append(fields);
  };

  const renderManualPanel = (panel, channel) => {
    const values = {
      title:
        panel.querySelector('input[name="youtube_title"]')?.value ||
        panel.querySelector('input[name="tiktok_title"]')?.value ||
        '',
      description: panel.querySelector('textarea[name="youtube_description"]')?.value || '',
      caption: panel.querySelector('textarea[name="tiktok_caption"]')?.value || '',
    };

    panel.dataset.manualMode = 'true';
    panel.innerHTML = '';

    const head = document.createElement('div');
    head.className = 'settings-head';
    const copy = document.createElement('div');
    const eyebrow = document.createElement('p');
    eyebrow.className = 'eyebrow';
    eyebrow.textContent = 'Без приложения';
    const title = document.createElement('h4');
    title.textContent = `Пакет для ${labels[channel] || channel}`;
    copy.append(eyebrow, title);
    head.append(copy);

    const text = document.createElement('p');
    text.className = 'muted';
    text.textContent =
      'После нажатия «Опубликовать» Bamboo подготовит отдельный текст и ZIP с выбранными медиа. В истории появится кнопка «Открыть пакет».';

    const note = document.createElement('p');
    note.className = 'field-help';
    note.textContent =
      'Видимость, музыка, рекламные отметки и другие параметры вы выберете уже в штатном интерфейсе площадки.';

    const link = document.createElement('a');
    link.className = 'button soft';
    link.href = '/connections';
    link.textContent = 'Изменить режим подключения';

    panel.append(head, text, note, link);
    preserveManualFormContract(panel, channel, values);
  };

  const init = async () => {
    for (const panel of document.querySelectorAll('[data-channel-settings]')) {
      const channel = panel.dataset.channelSettings;
      if (!['tiktok', 'youtube'].includes(channel)) continue;
      try {
        const response = await fetch(`/api/integrations/${channel}/health`);
        const body = await response.json();
        if (body?.capabilities?.automatic === false) renderManualPanel(panel, channel);
      } catch (_error) {
        // The normal API settings remain visible if the health request cannot be completed.
      }
    }
  };

  init();
})();
