(() => {
  'use strict';
  const labels = {
    display_name: '登録者名', title: 'タイトル', property_name: '物件名',
    material_type: '材の種類', quantity_level: '量の目安', quantity: '数量',
    size: '寸法', condition: '状態', description: '内容・コメント',
    usage_purpose: '使用目的', pickup_deadline: '受け渡し希望期限',
    registrant_type: '登録者の区分', demolition_date: '解体予定日',
    demolition_contractor: '解体業者', viewing_period: '見学期間',
    building_use: '建物用途', structure: '構造', floors: '階数',
    building_age: '築年数', condition_evaluation: '状態評価', notes: '備考',
  };
  const publicLocation = value => ['和泊町', '知名町'].find(town => value.includes(town))
    || (value === '島内どこでも可' ? value : '場所は問い合わせ後に相談');
  document.querySelectorAll('form[data-draft-kind]').forEach(form => {
    const submit = form.querySelector('button[type=submit]');
    if (submit) submit.textContent = '公開内容を確認する';
    const dialog = document.createElement('dialog');
    dialog.className = 'post-preview-dialog';
    dialog.setAttribute('aria-label', '投稿の公開内容を確認');
    const title = document.createElement('h2');
    title.textContent = 'この内容が公開されます';
    const hint = document.createElement('p');
    hint.textContent = '写真や本文に、公開したくない住所・氏名・連絡先が含まれていないか確認してください。';
    const body = document.createElement('div');
    const back = document.createElement('button');
    back.type = 'button'; back.className = 'secondary-button'; back.textContent = '入力に戻る';
    const confirm = document.createElement('button');
    confirm.type = 'button'; confirm.textContent = 'この内容で投稿する';
    dialog.append(title, hint, body, back, confirm);
    document.querySelector('main').append(dialog);
    let approved = false;
    let urls = [];
    const release = () => { urls.forEach(url => URL.revokeObjectURL(url)); urls = []; };
    back.addEventListener('click', () => dialog.close());
    dialog.addEventListener('close', release);
    let preparing = false;
    dialog.addEventListener('cancel', event => { if (preparing) event.preventDefault(); });
    confirm.addEventListener('click', async () => {
      if (preparing) return;
      preparing = true;
      confirm.disabled = true; back.disabled = true;
      confirm.textContent = '写真を準備しています…';
      try {
        await window.preparePostImages?.(form);
        dialog.close(); approved = true;
        form.requestSubmit(submit);
      } finally {
        approved = false; preparing = false;
        confirm.disabled = false; back.disabled = false;
        confirm.textContent = 'この内容で投稿する';
      }
    });
    form.addEventListener('submit', event => {
      if (event.defaultPrevented) return;
      if (approved) {
        queueMicrotask(() => {
          if (!event.defaultPrevented && submit) {
            submit.disabled = true; submit.textContent = '写真と投稿を保存しています…';
            form.setAttribute('aria-busy', 'true');
          }
        });
        return;
      }
      event.preventDefault();
      release(); body.replaceChildren();
      const data = new FormData(form);
      const details = document.createElement('dl'); details.className = 'detail-list';
      const add = (label, value) => {
        if (!value) return;
        const row = document.createElement('div');
        const dt = document.createElement('dt'); dt.textContent = label;
        const dd = document.createElement('dd'); dd.textContent = value;
        row.append(dt, dd); details.append(row);
      };
      add('公開する場所', publicLocation(String(data.get('location') || '').normalize('NFKC')));
      for (const [name, label] of Object.entries(labels)) add(label, data.get(name));
      body.append(details);
      for (const file of [...data.values()].filter(value => value instanceof File && value.size)) {
        const img = document.createElement('img'); img.alt = file.name;
        img.src = URL.createObjectURL(file); urls.push(img.src); body.append(img);
      }
      dialog.showModal(); back.focus();
    });
    window.addEventListener('pageshow', () => {
      form.removeAttribute('aria-busy');
      if (submit && submit.textContent === '写真と投稿を保存しています…') {
        submit.disabled = false; submit.textContent = '公開内容を確認する';
      }
    });
  });
})();
