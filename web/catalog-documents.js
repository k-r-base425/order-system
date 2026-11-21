  function field(label, type, value) {
    const wrap = el('label',label);
    const input = el('input');
    input.type = type;
    input.value = value || '';
    if (type === 'text') input.maxLength = 120;
    wrap.append(input);
    return {wrap,input};
  }

  function contactFields(data, forInvoice = false) {
    const group = el('div',undefined,'doc-fields');
    const to = field('宛名（任意）','text',data.recipient);
    const from = field('発行者（任意）','text',data.issuer);
    group.append(to.wrap,from.wrap);
    const details = el('details',undefined,'doc-options');
    details.append(el('summary','帳票の追加項目（任意）'));
    const optional = el('div',undefined,'doc-fields');
    const subject = field('件名','text',data.subject);
    const due = field(forInvoice ? '支払期限' : '見積有効期限','date','');
    const memo = field('備考','text',data.memo);
    const bank = field('振込先','text','');
    optional.append(subject.wrap,due.wrap);
    if (forInvoice) optional.append(bank.wrap);
    optional.append(memo.wrap);
    details.append(optional);
    group.append(details);
    return {group, values:() => ({
      recipient:to.input.value.trim(), issuer:from.input.value.trim(), subject:subject.input.value.trim(),
      due:due.input.value, memo:memo.input.value.trim(), ...(forInvoice ? {bank:bank.input.value.trim()} : {})
    })};
  }

  function templateLink() {
    const link = el('a','Excel雛形をダウンロード','template-link');
    link.href = 'document-template.xlsx';
    link.download = '帳票ひな型.xlsx';
    return link;
  }

  function docNumber(prefix,id) { return prefix + '-TEST-' + String(id).padStart(4,'0'); }
  function orderDate(order) { return order.date || issueDate(order.created); }
  function pricedItems(order) {
    return order.items.map(line => ({...line,unitPrice:line.unitPrice ?? legacyUnitPrice(line.code)}));
  }
  function amount(lines) { return lines.reduce((sum,line) => sum + line.qty * line.unitPrice,0); }

  async function documentPhotos(order) {
    const db = await database();
    const aliases = JSON.parse(get('#previous-photos').textContent);
    const photos = new Map();
    for (const src of new Set(order.items.map(item => item.image))) {
      const stored = await read(db.transaction('photos').objectStore('photos').get(src));
      const blob = stored instanceof ArrayBuffer ? new Blob([stored],{type:'image/jpeg'}) : stored;
      const url = blob ? URL.createObjectURL(blob) : src;
      if (blob) photoURLs.push(url);
      photos.set(src,{url,fallback:blob ? null : aliases[src]});
    }
    return photos;
  }

  function documentPhoto(item, photos) {
    const {url,fallback} = photos.get(item.image);
    const img = el('img');
    img.alt = item.code + ' の商品写真';
    if (fallback) img.addEventListener('error',() => { img.src = fallback; },{once:true});
    img.src = url;
    return img;
  }

  function fact(list,label,value) {
    const entry = el('div');
    entry.append(el('dt',label),el('dd',value || '—'));
    list.append(entry);
  }

  function financialSheet(order, lines, invoice) {
    const title = invoice ? '請求書' : '見積書';
    const data = invoice || order;
    const date = invoice?.date || orderDate(order);
    const page = el('article',undefined,'document-sheet financial-sheet');
    const header = el('div',undefined,'bill-header');
    header.append(el('h2',title));
    const meta = el('p', 'テスト注文　' + docNumber(invoice ? 'INV' : 'QT',order.id) + '　発行日 ' + date);
    header.append(meta);
    const parties = el('dl',undefined,'bill-parties');
    fact(parties,'宛名',data.recipient);
    fact(parties,'発行者',data.issuer);
    const terms = el('dl',undefined,'bill-terms');
    fact(terms,'件名',data.subject || 'Tシャツ商品代');
    fact(terms,'注文番号',number(order.id));
    if (invoice) fact(terms,'見積番号',docNumber('QT',order.id));
    fact(terms,invoice ? '支払期限' : '見積有効期限',data.due);
    if (invoice) fact(terms,'振込先',data.bank);
    const summary = el('div',undefined,'bill-amount');
    summary.append(el('span',invoice ? 'ご請求金額' : 'お見積金額'),el('strong',yen(amount(lines))));
    const table = el('table',undefined,'bill-lines');
    const heading = table.createTHead().insertRow();
    for (const label of ['摘要・品番','数量','単価（円）','金額（円）']) {
      const th = el('th',label);
      th.scope = 'col';
      heading.append(th);
    }
    const rows = table.createTBody();
    for (const item of [...lines].sort(byCode)) {
      const row = rows.insertRow();
      row.insertCell().append(el('strong',item.code),el('span',item.name));
      for (const value of [item.qty,item.unitPrice,item.qty * item.unitPrice]) {
        row.insertCell().textContent = value.toLocaleString('ja-JP');
      }
    }
    const total = el('p', '合計 ' + qtyTotal(lines).toLocaleString('ja-JP') + ' 点　' + yen(amount(lines)), 'bill-total');
    const notes = el('div',undefined,'bill-notes');
    notes.append(el('strong','備考'),el('p',data.memo || '—'));
    page.append(header,parties,terms,summary,table,total,notes);
    return page;
  }

  function photoSheet(order, lines, photos, invoice) {
    const page = el('article',undefined,'document-sheet photo-sheet');
    const date = invoice?.date || orderDate(order);
    const facts = el('dl',undefined,'document-facts');
    fact(facts,'注文番号',number(order.id));
    fact(facts,'見積番号',docNumber('QT',order.id));
    if (invoice) fact(facts,'請求番号',docNumber('INV',order.id));
    fact(facts,'発行日',date);
    fact(facts,'宛名',(invoice || order).recipient);
    page.append(el('small','テスト注文'),el('h2',invoice ? '画像付き注文確定リスト' : '画像付き注文票'),facts);
    const list = el('div',undefined,'photo-items');
    for (const item of [...lines].sort(byCode)) {
      const card = el('figure',undefined,'photo-item');
      const caption = el('figcaption');
      const top = el('div');
      top.append(el('strong',item.code),el('b',item.qty + ' 点'));
      caption.append(top,el('span',item.name),el('small',date + '　単価 ' + yen(item.unitPrice)),
                     el('small','小計 ' + yen(item.qty * item.unitPrice)));
      card.append(documentPhoto(item,photos),caption);
      list.append(card);
    }
    page.append(list,el('p','合計 ' + qtyTotal(lines).toLocaleString('ja-JP') + ' 点　' + yen(amount(lines)),'doc-total'));
    return page;
  }

  function preparePrint() {
    const target = get('#print-documents');
    target.replaceChildren(...Array.from(body.querySelectorAll('.document-sheet'),node => node.cloneNode(true)));
  }
  window.addEventListener('beforeprint',preparePrint);
  function printDocuments() {
    preparePrint();
    window.print();
  }
  // Safari の印刷プレビューを閉じた後も、画面では元の帳票を使う。
  window.addEventListener('afterprint',() => get('#print-documents').replaceChildren());

  function docActions() {
    const actions = el('div',undefined,'order-actions');
    body.append(actions);
    return actions;
  }

  async function showOrder(order) {
    panel('テスト注文 ' + number(order.id));
    const photos = await documentPhotos(order);
    const actions = docActions();
    actions.append(action('見積書・注文票をPDF保存／印刷',printDocuments,true),
      action(order.invoice ? '請求書を開く' : '請求書を作成',() => run(() =>
        order.invoice ? showInvoice(order) : editInvoice(order))),templateLink());
    const lines = pricedItems(order);
    body.append(financialSheet(order,lines),photoSheet(order,lines,photos));
  }

  async function showInvoice(order) {
    panel('請求書 ' + docNumber('INV',order.id));
    const photos = await documentPhotos(order);
    docActions().append(action('請求書・確定リストをPDF保存／印刷',printDocuments,true),
      action('見積書・注文書へ',() => run(() => showOrder(order))),templateLink());
    const billed = new Map(order.invoice.items.map(line => [line.code,line]));
    const lines = pricedItems(order).filter(line => billed.has(line.code)).map(line => ({...line,...billed.get(line.code)}));
    body.append(financialSheet(order,lines,order.invoice),photoSheet(order,lines,photos,order.invoice));
  }

  async function saveInvoice(order,invoice) {
    const db = await database();
    const tx = db.transaction('orders','readwrite');
    const done = completed(tx);
    const store = tx.objectStore('orders');
    const request = store.get(order.id);
    let latest;
    request.onsuccess = () => {
      latest = request.result;
      if (!latest) { tx.abort(); return; }
      if (!latest.invoice) {
        latest.invoice = invoice;
        store.put(latest);
      }
    };
    await done;
    return latest;
  }

  async function editInvoice(order) {
    panel('請求書を作成');
    const photos = await documentPhotos(order);
    const lines = pricedItems(order);
    body.append(el('p','注文 ' + number(order.id) + ' ／ 見積 ' + docNumber('QT',order.id),'results'));
    const form = el('form',undefined,'invoice-form');
    const contacts = contactFields(order,true);
    const date = field('請求書の発行日','date',issueDate());
    date.input.required = true;
    contacts.group.append(date.wrap);
    form.append(contacts.group,el('h3','入荷数の照合'),
      el('p','写真と手元の商品を照合し、実際に届いた点数に合わせてください。0点の商品は請求対象から外れます。','results'));
    const quotedTotal = amount(lines);
    const total = el('p',undefined,'doc-total');
    const save = el('button','テスト請求書を発行','action primary');
    save.type = 'submit';
    const updateTotal = () => {
      total.textContent = '見積合計 ' + yen(quotedTotal) + ' ／ 請求合計 ' + qtyTotal(lines).toLocaleString('ja-JP') + ' 点　' + yen(amount(lines));
      save.disabled = !qtyTotal(lines);
    };
    for (const line of [...lines].sort(byCode)) {
      const row = el('div',undefined,'invoice-line');
      const copy = el('div',undefined,'item-copy');
      copy.append(el('strong',line.code),el('small',line.name),el('small','見積 ' + line.qty + ' 点　単価 ' + yen(line.unitPrice)));
      const controls = el('div',undefined,'invoice-qty');
      const count = el('output');
      const sub = el('strong');
      const limit = line.qty;
      const adjust = delta => { line.qty += delta; render(); updateTotal(); };
      const minus = action('−',() => adjust(-1));
      const plus = action('＋',() => adjust(1));
      minus.setAttribute('aria-label',line.code + ' の請求点数を減らす');
      plus.setAttribute('aria-label',line.code + ' の請求点数を増やす');
      function render() {
        count.value = '入荷 ' + line.qty + ' 点';
        sub.textContent = yen(line.qty * line.unitPrice);
        minus.disabled = line.qty === 0;
        plus.disabled = line.qty === limit;
      }
      controls.append(minus,count,plus,sub);
      row.append(documentPhoto(line,photos),copy,controls);
      form.append(row);
      render();
    }
    updateTotal();
    const actions = el('div',undefined,'order-actions');
    actions.append(save,action('見積書・注文書に戻る',() => run(() => showOrder(order))));
    form.append(total,actions);
    form.onsubmit = event => {
      event.preventDefault();
      if (!date.input.value || !qtyTotal(lines)) return;
      run(async () => {
        const items = lines.filter(line => line.qty > 0).map(({code,qty,unitPrice}) => ({code,qty,unitPrice}));
        const latest = await saveInvoice(order,{date:date.input.value,...contacts.values(),items});
        await history();
        await showInvoice(latest);
      });
    };
    body.append(form);
  }
