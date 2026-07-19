(function () {
  const presetConfigs = {
    board: {
      preview: '例: L1800×W90×t30mm',
      fields: [
        { key: 'length', label: '長さ', placeholder: '1800' },
        { key: 'width', label: '幅', placeholder: '90' },
        { key: 'thickness', label: '厚み', placeholder: '30' },
      ],
      build(values) {
        return `L${values.length}×W${values.width}×t${values.thickness}${values.unit}`;
      },
    },
    square: {
      preview: '例: L1800×□90mm',
      fields: [
        { key: 'length', label: '長さ', placeholder: '1800' },
        { key: 'section', label: '断面一辺', placeholder: '90' },
      ],
      build(values) {
        return `L${values.length}×□${values.section}${values.unit}`;
      },
    },
    door: {
      preview: '例: W850×H2000mm',
      fields: [
        { key: 'width', label: '幅', placeholder: '850' },
        { key: 'height', label: '高さ', placeholder: '2000' },
      ],
      build(values) {
        return `W${values.width}×H${values.height}${values.unit}`;
      },
    },
    round: {
      preview: '例: φ60×L2400mm',
      fields: [
        { key: 'diameter', label: '直径', placeholder: '60' },
        { key: 'length', label: '長さ', placeholder: '2400' },
      ],
      build(values) {
        return `φ${values.diameter}×L${values.length}${values.unit}`;
      },
    },
    pipe: {
      preview: '例: L2000×φ27×t2.3mm',
      fields: [
        { key: 'length', label: '長さ', placeholder: '2000' },
        { key: 'outerDiameter', label: '外径', placeholder: '27' },
        { key: 'thickness', label: '肉厚', placeholder: '2.3' },
      ],
      build(values) {
        return `L${values.length}×φ${values.outerDiameter}×t${values.thickness}${values.unit}`;
      },
    },
  };

  function normalizeText(value) {
    return String(value || '').trim();
  }

  function setPanelVisibility(root, mode) {
    root.querySelectorAll('[data-size-panel]').forEach((panel) => {
      panel.hidden = panel.dataset.sizePanel !== mode;
    });

    root.querySelectorAll('[data-size-mode-button]').forEach((button) => {
      const active = button.dataset.sizeModeButton === mode;
      button.classList.toggle('is-active', active);
      button.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  function readStructuredValues(panel) {
    const values = {
      unit: panel.querySelector('[data-size-unit]')?.value || 'mm',
    };

    panel.querySelectorAll('[data-size-field]').forEach((input) => {
      values[input.dataset.sizeField] = normalizeText(input.value);
    });

    return values;
  }

  function updateSizeState(root) {
    const modeSelect = root.querySelector('[data-size-mode-select]');
    const hiddenInput = root.querySelector('[data-size-hidden]');
    const preview = root.querySelector('[data-size-preview]');
    const freeInput = root.querySelector('[data-size-free]');

    if (!modeSelect || !hiddenInput || !preview) {
      return;
    }

    const mode = modeSelect.value || 'free';
    setPanelVisibility(root, mode);

    if (mode === 'free') {
      const value = normalizeText(freeInput?.value || '');
      hiddenInput.value = value;
      preview.textContent = value ? `入力内容: ${value}` : '自由記入で寸法を入力してください。';
      return;
    }

    const panel = root.querySelector(`[data-size-panel="${mode}"]`);
    const config = presetConfigs[mode];
    if (!panel || !config) {
      const fallback = normalizeText(freeInput?.value || '');
      hiddenInput.value = fallback;
      preview.textContent = fallback ? `入力内容: ${fallback}` : '寸法を入力してください。';
      return;
    }

    const values = readStructuredValues(panel);
    const hasAnyValue = config.fields.some((field) => values[field.key]);
    const composed = hasAnyValue ? config.build(values) : '';
    hiddenInput.value = composed;
    preview.textContent = composed || config.preview;
  }

  function initializePanel(root) {
    const modeSelect = root.querySelector('[data-size-mode-select]');
    if (!modeSelect || root.dataset.sizeBuilderReady === 'true') {
      return;
    }

    root.dataset.sizeBuilderReady = 'true';

    modeSelect.addEventListener('change', () => updateSizeState(root));

    root.querySelectorAll('[data-size-mode-button]').forEach((button) => {
      button.addEventListener('click', () => {
        modeSelect.value = button.dataset.sizeModeButton || 'free';
        updateSizeState(root);
      });
    });

    root.querySelectorAll('[data-size-free], [data-size-field], [data-size-unit]').forEach((input) => {
      input.addEventListener('input', () => updateSizeState(root));
      input.addEventListener('change', () => updateSizeState(root));
    });

    const initialMode = root.dataset.sizeInitialMode || modeSelect.value || 'free';
    modeSelect.value = initialMode;
    updateSizeState(root);
  }

  function initMaterialSizeBuilders(scope = document) {
    scope.querySelectorAll('[data-size-builder]').forEach((root) => initializePanel(root));
  }

  window.initMaterialSizeBuilders = initMaterialSizeBuilders;
  window.updateMaterialSizeBuilder = updateSizeState;
})();