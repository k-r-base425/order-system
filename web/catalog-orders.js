(() => {
  'use strict';
  const tabs = Array.from(document.querySelectorAll('[data-view]'));
  const orderDialog = get('#order-dialog');
  const body = get('#order-body');
  const pick = get('#pick');
  const products = new Map(cards.map(card => [card.dataset.code, {
    code: card.dataset.code,
    name: card.querySelector('.name').textContent,
    image: card.querySelector('img').getAttribute('src')
  }]));
  let view = 'catalog';
  let draft = [];
  let dbPromise;
  let busy = false;
  let messageTimer;
  let photoURLs = [];

  function database() {
    if (!dbPromise) dbPromise = new Promise((resolve, reject) => {
      // GitHub Pages の同一ドメインにある別アプリとは台帳を共有しない。
      const open = indexedDB.open('band-shirt-test-orders:' + new URL('.', location.href).pathname, 1);
      open.onupgradeneeded = () => {
        const db = open.result;
        db.createObjectStore('draft', {keyPath:'code'});
        db.createObjectStore('orders', {keyPath:'id', autoIncrement:true});
        db.createObjectStore('photos');
      };
      open.onsuccess = () => resolve(open.result);
      open.onerror = () => reject(open.error);
    }).catch(error => { dbPromise = null; throw error; });
    return dbPromise;
  }
  function read(request) {
    return new Promise((resolve,reject) => {
      request.onsuccess = () => resolve(request.result);
      request.onerror = () => reject(request.error);
    });
  }
  function completed(tx) {
    return new Promise((resolve,reject) => {
      tx.oncomplete = resolve;
      tx.onabort = () => reject(tx.error || new Error('注文内容が変わりました。再確認してください。'));
      tx.onerror = () => {}; // abort で確定した結果を通知する。
    });
  }
  async function all(store) {
    const db = await database();
    return read(db.transaction(store).objectStore(store).getAll());
  }
  function qtyTotal(lines) { return lines.reduce((sum, line) => sum + line.qty, 0); }
  function number(id) { return 'TEST-' + String(id).padStart(4,'0'); }
  function dateLabel(created) { return new Date(created).toLocaleString('ja-JP',{dateStyle:'short',timeStyle:'short'}); }
  function el(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function action(text, handler, primary = false) {
    const btn = el('button',text,'action' + (primary ? ' primary' : ''));
    btn.type = 'button';
    btn.onclick = handler;
    return btn;
  }
  function notice(text) {
    const n = get('#order-message');
    n.textContent = text; n.hidden = false;
    clearTimeout(messageTimer);
    messageTimer = setTimeout(() => n.hidden = true,3500);
  }
  function errorMessage(text) {
    const node = orderDialog.open ? get('#order-error') : detail.open ? get('#pick-error') : get('#order-message');
    clearTimeout(messageTimer);
    node.textContent = text;
    node.hidden = false;
  }
  async function run(fn) {
    if (busy) return;
    busy = true;
    document.querySelector("main").inert = true;
    try { await fn(); }
    catch (error) {
      errorMessage(error.name === 'QuotaExceededError' ? '保存容量が足りません。カートを保持しました。' :
        (error.name === 'Error' ? error.message : '保存領域を利用できません。通常のブラウザで開き直してください。'));
    } finally { busy = false; document.querySelector("main").inert = false; }
  }
  function updateBar() {
    get('#cart-bar').textContent = 'カートを確認　' + qtyTotal(draft) + ' 点';
  }
  async function changeDraft(code, qty, previous) {
    if (!Number.isInteger(qty) || qty < 0 || qty > 99999) throw new Error('点数は1〜99,999で入力してください。');
    const db = await database();
    const tx = db.transaction('draft','readwrite');
    const done = completed(tx);
    const store = tx.objectStore('draft');
    const req = store.get(code);
    req.onsuccess = () => {
      if ((req.result?.qty || 0) !== previous) { tx.abort(); return; }
      if (qty) store.put({...products.get(code),qty});
      else store.delete(code);
    };
    try { await done; }
    finally { draft = await all('draft'); updateBar(); }
  }
  function configurePick() {
    pick.hidden = view !== 'create';
    get('#pick-error').hidden = true;
    if (!selected) return;
    const existing = draft.find(row => row.code === selected.dataset.code)?.qty || 0;
    pick.elements.qty.value = existing || 1;
    pick.dataset.previous = existing;
    pick.querySelector('button').textContent = existing ? '点数を更新' : 'カートに追加';
  }
  detail.addEventListener('productchange',configurePick);
  pick.onsubmit = event => {
    event.preventDefault();
    run(async () => {
      const code = selected.dataset.code;
      await changeDraft(code,pick.elements.qty.valueAsNumber,Number(pick.dataset.previous));
      detail.close(); notice(code + ' をカートに保存しました。');
    });
  };
  function releaseURLs() { photoURLs.forEach(url => URL.revokeObjectURL(url)); photoURLs = []; }
  orderDialog.addEventListener('close',() => { if (!orderDialog.open) releaseURLs(); });
  orderDialog.addEventListener('cancel',event => { if (busy) event.preventDefault(); });
  get('#order-close').onclick = () => { if (!busy) orderDialog.close(); };
  function panel(title) {
    releaseURLs(); body.replaceChildren(); get('#order-title').textContent = title;
    get('#order-error').hidden = true;
    if (!orderDialog.open) orderDialog.showModal();
    orderDialog.scrollTop = 0;
  }
  function productLine(line, src) {
    const row = el('div',undefined,'order-line');
    const img = el('img'); img.src = src; img.alt = line.code + ' の商品写真';
    const desc = el('div',undefined,'item-copy');
    desc.append(el('strong',line.code),el('small',line.name));
    row.append(img,desc,el('strong',line.qty + ' 点'));
    return row;
  }
  function drawCart() {
    panel('テスト注文の確認');
    if (!draft.length) { body.append(el('p','カートは空です。商品を選び、点数を入力してください。')); return; }
    for (const line of draft) {
      const row = productLine(line,line.image);
      const edit = action('変更',() => {
        orderDialog.close();
        const card = cards.find(c => c.dataset.code === line.code);
        if (card) {
          search.value = line.code;
          filters.find(b => b.dataset.filter === 'all').click();
          show(card);
        }
      });
      const remove = action('削除',() => run(async () => {
        await changeDraft(line.code,0,line.qty); drawCart();
      }));
      row.append(edit,remove); body.append(row);
    }
    body.append(el('p','合計 ' + qtyTotal(draft) + ' 点'));
    body.append(el('p','この端末にテスト注文として保存します。仕入先への送信はありません。','test-note'));
    const save = action('テスト注文を確定',() => run(async () => {
      save.disabled = true; save.textContent = '保存中…';
      try {
        const order = await checkout(draft);
        await changeView('history');
        await showOrder(order);
      } finally { save.disabled = false; save.textContent = 'テスト注文を確定'; }
    }),true);
    body.append(save);
  }
  // 注文時の写真を端末に保存する。画像が差し替わっても履歴は同じ写真を使う。
  async function checkout(lines) {
    if (!lines.length) throw new Error('商品を選んでください。');
    const db = await database();
    const photos = new Map();
    if (location.protocol !== 'file:') {
      for (const src of new Set(lines.map(line => line.image))) {
        const exists = await read(db.transaction('photos').objectStore('photos').getKey(src));
        if (exists !== undefined) continue;
        const resp = await fetch(src);
        if (!resp.ok || !resp.headers.get('Content-Type')?.startsWith('image/')) throw new Error('商品写真を取得できません。通信を確認し、もう一度お試しください。');
        photos.set(src,await resp.blob());
      }
    }
    const tx = db.transaction(['orders','draft','photos'],'readwrite');
    const done = completed(tx);
    const current = tx.objectStore('draft').getAll();
    const order = {type:'test',created:new Date().toISOString(),items:lines,total:qtyTotal(lines)};
    current.onsuccess = () => {
      if (JSON.stringify(current.result) !== JSON.stringify(lines)) { tx.abort(); return; }
      photos.forEach((blob,key) => tx.objectStore('photos').put(blob,key));
      const req = tx.objectStore('orders').add(order);
      req.onsuccess = () => { order.id = req.result; };
      tx.objectStore('draft').clear();
    };
    try { await done; } catch (error) {
      draft = await all('draft'); updateBar(); drawCart(); throw error;
    }
    draft = []; updateBar();
    return order;
  }
  async function showOrder(order) {
    panel('テスト注文 ' + number(order.id));
    body.append(el('p',dateLabel(order.created) + '　合計 ' + order.total + ' 点'));
    const db = await database();
    for (const item of order.items) {
      const blob = await read(db.transaction('photos').objectStore('photos').get(item.image));
      const url = blob ? URL.createObjectURL(blob) : item.image;
      if (blob) photoURLs.push(url);
      body.append(productLine(item,url));
    }
    const buttons = el('div',undefined,'order-actions');
    buttons.append(action('印刷・PDF保存',() => window.print()));
    body.append(buttons);
  }
  async function history() {
    const list = get('#history-list');
    const orders = await all('orders');
    list.replaceChildren();
    get('#history-empty').hidden = orders.length > 0;
    for (const order of orders.reverse()) {
      const btn = el('button',undefined,'history-row');
      const label = el('span','テスト注文 ' + number(order.id));
      label.append(el('small',dateLabel(order.created)));
      btn.append(label,el('strong',order.total + ' 点　›'));
      btn.onclick = () => run(() => showOrder(order));
      list.append(btn);
    }
  }
  async function changeView(next) {
    view = next;
    tabs.forEach(b => {
      if (b.dataset.view === next) b.setAttribute('aria-current','page');
      else b.removeAttribute('aria-current');
    });
    get('#test-note').hidden = next === 'catalog';
    get('#catalog-view').hidden = next === 'history';
    get('#history-view').hidden = next !== 'history';
    get('#cart-bar').hidden = next !== 'create';
    get('#order-message').hidden = true;
    if (next === 'create') { draft = await all('draft'); updateBar(); }
    if (next === 'history') await history();
    window.scrollTo(0,0);
  }
  tabs.forEach(b => b.onclick = () => run(() => changeView(b.dataset.view)));
  get('#cart-bar').onclick = () => run(async () => { draft = await all('draft'); updateBar(); drawCart(); });
})();
