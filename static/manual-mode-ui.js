(() => {
  const labels = {
    tiktok: 'TikTok',
    youtube: 'YouTube',
  };

  const renderManualPanel = (panel, channel) => {
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
