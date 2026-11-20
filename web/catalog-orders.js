(() => {
  'use strict';
  const tabs = Array.from(document.querySelectorAll('[data-view]'));
  const orderDialog = get('#order-dialog');
  const body = get('#order-body');
  const pickSheet = get('#pick-sheet');
  const pickOpen = get('#pick-open');
  let pickQty = 1;
  let previousQty = 0;
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
      const open = indexedDB.open('band-shirt-test-orders:' + new URL('.', location.href).pathname, 2);
      open.onupgradeneeded = event => {
        const db = open.result;
        if (event.oldVersion === 0) {
          db.createObjectStore('draft', {keyPath:'code'});
          db.createObjectStore('orders', {keyPath:'id', autoIncrement:true});
          db.createObjectStore('photos');
          return;
        }
        // 旧カートだけを変換する。確定済みの注文・写真は当時のままにする。
        const store = open.transaction.objectStore('draft');
        const request = store.getAll();
        request.onsuccess = () => {
          const mapping = JSON.parse(get('#previous-codes').textContent);
          const merged = new Map();
          for (const line of request.result) {
            const product = products.get(mapping[line.code]);
            if (!product) {
              open.transaction.abort();
              return;
            }
            const qty = (merged.get(product.code)?.qty || 0) + line.qty;
            merged.set(product.code, {...product, qty});
          }
          store.clear();
          for (const line of merged.values()) store.put(line);
        };
      };
      open.onblocked = () => errorMessage('以前の注文画面をほかのタブで開いている場合は、そのタブを閉じてください。');
      open.onsuccess = () => {
        const db = open.result;
        db.onversionchange = () => { db.close(); dbPromise = null; };
        resolve(db);
      };
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
    const node = orderDialog.open ? get('#order-error') : pickSheet.open ? get('#pick-error') : get('#order-message');
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
    pickOpen.hidden = view !== 'create';
    const existing = draft.find(row => row.code === selected.dataset.code);
    pickOpen.textContent = existing ? '注文数を変更（' + existing.qty + '点）' : '注文数を選ぶ';
  }
  detail.addEventListener('productchange',configurePick);

  function setPickQty(qty) {
    pickQty = qty;
    get('#pick-qty').value = qty.toLocaleString('ja-JP') + ' 点';
    get('#pick-minus').disabled = qty <= 1;
    get('#pick-plus').disabled = qty >= 99999;
  }
  function showPickStep(review) {
    get('#pick-title').textContent = review ? '追加内容の確認' : '注文数を選ぶ';
    get('#pick-minus').hidden = get('#pick-plus').hidden = review;
    get('#pick-review').hidden = review;
    get('#pick-back').hidden = get('#pick-save').hidden = !review;
    get('#pick-amount').hidden = !review;
    if (review) {
      const unitPrice = selected.dataset.code.startsWith('SS') ? 2000 : 2900;
      get('#pick-amount strong').textContent = (pickQty * unitPrice).toLocaleString('ja-JP') + ' 円';
      get('#pick-save').textContent = previousQty ? 'カートの点数を更新' : 'カートに追加';
      if (previousQty) get('#pick-title').textContent = '変更内容の確認';
    }
    if (pickSheet.open) get('#pick-title').focus();
  }
  pickOpen.onclick = () => {
    const code = selected.dataset.code;
    const product = products.get(code);
    previousQty = draft.find(row => row.code === code)?.qty || 0;
    get('#pick-photo').src = product.image;
    get('#pick-code').textContent = code;
    get('#pick-name').textContent = product.name;
    get('#pick-sleeve').textContent = get('#detail-sleeve').textContent;
    get('#pick-sleeve').className = get('#detail-sleeve').className;
    get('#pick-error').hidden = true;
    setPickQty(previousQty || 1);
    showPickStep(false);
    pickSheet.showModal();
  };
  get('#pick-minus').onclick = () => setPickQty(pickQty - 1);
  get('#pick-plus').onclick = () => setPickQty(pickQty + 1);
  get('#pick-close').onclick = () => { if (!busy) pickSheet.close(); };
  pickSheet.addEventListener('cancel',event => { if (busy) event.preventDefault(); });
  get('#pick-review').onclick = () => showPickStep(true);
  get('#pick-back').onclick = () => { if (!busy) showPickStep(false); };
  get('#pick-save').onclick = () => run(async () => {
    const code = selected.dataset.code;
    const save = get('#pick-save');
    save.disabled = true;
    try {
      await changeDraft(code,pickQty,previousQty);
      pickSheet.close();
      detail.close();
      notice(code + ' をカートに保存しました。');
    } finally {
      save.disabled = false;
      configurePick();
    }
  });
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
    if (!draft.length) { body.append(el('p','カートは空です。商品を選び、点数を選んでください。')); return; }
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
        // WebKitのプライベート閲覧でも写真を保存できるよう、バイト列を使う。
        photos.set(src,await resp.arrayBuffer());
      }
    }
    const tx = db.transaction(['orders','draft','photos'],'readwrite');
    const done = completed(tx);
    const current = tx.objectStore('draft').getAll();
    const order = {type:'test',created:new Date().toISOString(),items:lines,total:qtyTotal(lines)};
    current.onsuccess = () => {
      if (JSON.stringify(current.result) !== JSON.stringify(lines)) { tx.abort(); return; }
      photos.forEach((bytes,key) => tx.objectStore('photos').put(bytes,key));
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
    const photoAliases = JSON.parse(get('#previous-photos').textContent);
    for (const item of order.items) {
      const stored = await read(db.transaction('photos').objectStore('photos').get(item.image));
      const blob = stored instanceof ArrayBuffer ? new Blob([stored], {type:'image/jpeg'}) : stored;
      const url = blob ? URL.createObjectURL(blob) : item.image;
      if (blob) photoURLs.push(url);
      const row = productLine(item,url);
      if (!blob && photoAliases[item.image]) {
        const img = row.querySelector('img');
        img.addEventListener('error', () => { img.src = photoAliases[item.image]; }, {once:true});
      }
      body.append(row);
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
