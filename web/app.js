"use strict";

const $ = selector => document.querySelector(selector);
const $$ = selector => Array.from(document.querySelectorAll(selector));
const dialog = $("#dialog");
const state = {products: [], draft: {}, orders: [], revision: null, price_classes: []};
let productsByCode = new Map();
let sleeveFilter = "";
let editMode = "replace";
let busy = false;
let initialized = false;
let previewURL = "";
let noticeTimeout;

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, char => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
  })[char]);
}

function sleeveChip(code) {
  return code.startsWith("SS")
    ? '<span class="chip">半袖</span>'
    : '<span class="chip long">長袖</span>';
}

function message(text, error = false) {
  const box = dialog.open ? $("#dialog-message") : $("#notice");
  clearTimeout(noticeTimeout);
  box.hidden = !text;
  box.textContent = text;
  box.classList.toggle("error", error);
  if (!dialog.open && text && !error) {
    noticeTimeout = setTimeout(() => { box.hidden = true; }, 4800);
  }
}

async function api(url, data) {
  const options = data === undefined ? {} : {
    method: "POST",
    headers: {"Content-Type": "application/json"},
    body: JSON.stringify(data)
  };
  let response;
  try {
    response = await fetch(url, {...options, cache: "no-store"});
  } catch {
    throw new Error("接続できませんでした。注文台帳が起動しているか確認してください。");
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const error = new Error(result.error || "処理に失敗しました。再度お試しください。");
    error.status = response.status;
    throw error;
  }
  return result;
}

async function refresh() {
  const data = await api("/api/state");
  Object.assign(state, data);
  productsByCode = new Map(state.products.map(product => [product.code, product]));
  initialized = true;
  const select = $("#replace-code");
  const previousCode = select.value;
  select.replaceChildren(...state.products.map(product =>
    new Option(product.code + "  " + product.name, product.code)));
  if (productsByCode.has(previousCode)) select.value = previousCode;
  renderCards();
  renderCart();
  renderHistory();
  renderPriceClasses();
}

const PRICE_SAVED = "単価を保存しました。照合用一覧を再出力すると、このPCで確認できます。確定済みの注文の単価は変わりません。";

function yen(value) {
  return Number(value).toLocaleString("ja-JP") + "円";
}

function renderPriceClasses() {
  const list = $("#price-class-list");
  list.replaceChildren(...state.price_classes.map(item => {
    const form = document.createElement("form");
    form.className = "pc-row";
    form.dataset.id = item.id;
    const labelField = document.createElement("label");
    labelField.append("区分名");
    const labelInput = document.createElement("input");
    labelInput.type = "text";
    labelInput.maxLength = 40;
    labelInput.required = true;
    labelInput.value = item.label;
    labelField.append(labelInput);
    const priceField = document.createElement("label");
    priceField.append("単価（円）");
    const priceInput = document.createElement("input");
    priceInput.type = "number";
    priceInput.min = "0";
    priceInput.max = "9999999";
    priceInput.step = "1";
    priceInput.required = true;
    priceInput.value = item.unit_price;
    priceField.append(priceInput);
    const save = document.createElement("button");
    save.type = "submit";
    save.className = "secondary";
    save.textContent = "保存";
    form.append(labelField, priceField, save);
    if (item.id === "SS" || item.id === "LS") {
      const note = document.createElement("small");
      note.className = "pc-note";
      note.textContent = "袖の標準";
      form.append(note);
    }
    form.onsubmit = event => {
      event.preventDefault();
      savePriceClass({id: item.id, label: labelInput.value.trim(), unit_price: Number(priceInput.value)});
    };
    return form;
  }));
  const select = $("#assign-class");
  select.replaceChildren(new Option("袖の標準（半袖・長袖）", ""),
    ...state.price_classes.map(item =>
      new Option(item.label + "  " + yen(item.unit_price), item.id)));
  const codeSelect = $("#assign-code");
  const previousCode = codeSelect.value;
  codeSelect.replaceChildren(...state.products.map(product =>
    new Option(product.code + "  " + product.name, product.code)));
  if (productsByCode.has(previousCode)) codeSelect.value = previousCode;
  syncAssignClass();
}

function syncAssignClass() {
  const product = productsByCode.get($("#assign-code").value);
  const wanted = product?.assigned_price_class || "";
  const select = $("#assign-class");
  select.value = Array.from(select.options).some(option => option.value === wanted) ? wanted : "";
}

function savePriceClass(body) {
  run(async () => {
    await api("/api/price-classes", {...body, revision: state.revision});
    await refresh();
    message(PRICE_SAVED);
  });
}

async function run(action) {
  if (busy) return;
  busy = true;
  const controls = [document.querySelector("main"), $("nav"), $("#dialog-body")];
  controls.forEach(control => control.inert = true);
  $("#close-dialog").disabled = true;
  try {
    await action();
  } catch (error) {
    if (error.status === 409) {
      if (dialog.open) dialog.close();
      try {
        await refresh();
        message("別の画面で内容が更新されました。最新の台帳を表示しています。", true);
      } catch (refreshError) {
        message(refreshError.message, true);
      }
    } else {
      message(error.message, true);
    }
  } finally {
    busy = false;
    controls.forEach(control => control.inert = false);
    $("#close-dialog").disabled = false;
  }
}

function fold(value) {
  return value.normalize('NFKC').toLowerCase()
    .replace(/[ぁ-ゖ]/g, c => String.fromCharCode(c.charCodeAt(0) + 0x60))
    .replace(/[\s・.'’/＆&-]/g, '');
}

function renderCards() {
  const query = fold($("#search").value);
  const shown = state.products.filter(product =>
    product.code.startsWith(sleeveFilter) &&
    fold(product.code + " " + product.name).includes(query));
  $("#product-count").textContent = query || sleeveFilter
    ? shown.length + " / " + state.products.length + " 商品"
    : "全 " + state.products.length + " 商品";
  $("#cards").innerHTML = shown.length ? shown.map(product => {
    const code = escapeHtml(product.code);
    const count = state.draft[product.code] || 0;
    return `<button class="card" data-product="${code}" aria-label="${code} ${escapeHtml(product.name)} の詳細">
      <img class="photo" loading="lazy" decoding="async" src="${escapeHtml(product.image)}" alt="">
      ${count ? `<span class="selected">${count} 点選択中</span>` : ""}
      <span class="card-info"><span class="card-code"><strong class="code">${code}</strong>${sleeveChip(code)}</span>
      <span class="item-name">${escapeHtml(product.name)}</span></span></button>`;
  }).join("") : '<p class="empty">該当する商品はありません。</p>';
}

function cartItems() {
  return Object.entries(state.draft).map(([code, qty]) => ({...productsByCode.get(code), qty}));
}

function sumQty(items) {
  return items.reduce((sum, item) => sum + item.qty, 0);
}

function renderCart() {
  const lines = cartItems();
  $("#save-status").textContent = initialized && lines.length ? "下書き保存済み" : "";
  $("#cart-total").textContent = sumQty(lines) + " 点";
  $("#review").disabled = !lines.length;
  $("#cart-lines").innerHTML = lines.length ? lines.map(item => {
    const code = escapeHtml(item.code);
    return `<div class="cart-row" data-code="${code}">
      <img src="${escapeHtml(item.image)}" alt="${code} の写真">
      <div><div class="line-info"><strong class="code">${code}</strong>${sleeveChip(code)}</div>
      <div class="item-name">${escapeHtml(item.name)}</div>
      <div class="line-controls"><div class="stepper">
        <button data-cart="minus" aria-label="${code} を1点減らす" ${item.qty <= 1 ? "disabled" : ""}>−</button>
        <button class="count-button" data-cart="edit" aria-label="${code} の点数を変更">${item.qty} 点</button>
        <button data-cart="plus" aria-label="${code} を1点増やす" ${item.qty >= 99999 ? "disabled" : ""}>＋</button>
      </div><button class="remove" data-cart="remove" aria-label="${code} を削除">削除</button></div></div></div>`;
  }).join("") : '<p class="empty">商品を選んで点数を入力してください。</p>';
}

function renderHistory() {
  $("#history-list").innerHTML = state.orders.length ? state.orders.map(order =>
    `<article class="history-row"><div><strong>注文 #${escapeHtml(order.id)}</strong>
    <small>${escapeHtml(displayTime(order.created))}</small></div>
    <span class="history-amount">${order.total} 点</span>
    <button data-order="${Number(order.id)}">注文を開く</button></article>`
  ).join("") : '<p class="empty">確定した注文がここに表示されます。</p>';
}

function displayTime(value) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : new Intl.DateTimeFormat("ja-JP", {
    dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Tokyo"
  }).format(date);
}

function showDialog(title, content) {
  $("#dialog-title").textContent = title;
  $("#dialog-body").innerHTML = content;
  $("#dialog-message").hidden = true;
  if (!dialog.open) dialog.showModal();
  dialog.scrollTop = 0;
}

function showProduct(code) {
  const item = productsByCode.get(code);
  if (!item) return;
  const existing = state.draft[code] || 0;
  showDialog("商品詳細", `
    <img class="dialog-photo" src="${escapeHtml(item.image)}" alt="${escapeHtml(code)} の写真">
    <div class="detail-heading"><strong class="code">${escapeHtml(code)}</strong>${sleeveChip(code)}</div>
    <div>${escapeHtml(item.name)}</div>
    <form id="select-product"><label class="qty-label">注文点数
      <input id="quantity" type="number" inputmode="numeric" step="1" min="1" max="99999" required value="${existing || 1}">
    </label><button class="primary" type="submit">${existing ? "点数を更新" : "カートに追加"}</button></form>`);
  $("#select-product").addEventListener("submit", event => {
    event.preventDefault();
    const qty = $("#quantity").valueAsNumber;
    if (!Number.isSafeInteger(qty) || qty < 1) {
      message("点数は1以上の整数で入力してください。", true);
      return;
    }
    run(async () => {
      await saveQty(code, qty);
      dialog.close();
      message(code + " を " + qty + " 点で保存しました。");
    });
  });
}

async function saveQty(code, qty) {
  const result = await api("/api/draft", {code, qty, revision: state.revision});
  state.draft = result.draft;
  state.revision = result.revision;
  renderCart();
  renderCards();
}

function orderLines(items) {
  return items.map(item =>
    `<div class="order-row"><img src="${escapeHtml(item.image)}" alt="${escapeHtml(item.code)} の写真">
      <div><div class="line-info"><strong class="code">${escapeHtml(item.code)}</strong>${sleeveChip(item.code)}</div>
      <div class="item-name">${escapeHtml(item.name)}</div></div><strong>${item.qty} 点</strong></div>`
  ).join("");
}

function totalRow(total) {
  return `<div class="order-summary"><span>合計点数</span><strong>${total} 点</strong></div>`;
}

function reviewDraft() {
  const items = cartItems();
  if (!items.length) return;
  showDialog("注文内容の確認", orderLines(items) + totalRow(sumQty(items)) +
    `<p class="muted">この内容を注文履歴に保存します。</p>
    <div class="dialog-actions"><button id="confirm-order" class="primary">注文を確定して保存</button>
    <button id="back" class="secondary">カートへ戻る</button></div>`);
  $("#back").onclick = () => dialog.close();
  $("#confirm-order").onclick = () => run(async () => {
    const order = await api("/api/orders", {revision: state.revision});
    // Once the server confirms, the same confirmation control must not be reused.
    showDialog("注文を保存しました", `<p>注文 #${Number(order.id)} を保存しました。</p>`);
    await refresh();
    await showOrder(order.id);
  });
}

async function showOrder(id) {
  const openOrder = await api("/api/orders/" + Number(id));
  const items = openOrder.items;
  const quantities = countsBySleeve(items);
  showDialog("注文 #" + openOrder.id, `
    <p class="muted">${escapeHtml(displayTime(openOrder.created))}</p>
    ${orderLines(items)}${totalRow(openOrder.total)}
    <p class="muted">見積用枚数　半袖 ${quantities[0]} 点 ／ 長袖 ${quantities[1]} 点</p>
    <div class="dialog-actions"><a class="primary-link" href="/api/orders/${Number(openOrder.id)}/pdf" target="_blank" rel="noopener">${openOrder.has_quote_pdf ? "見積書・写真付き注文書PDF" : "写真付き注文書PDF"}</a>
    <button id="copy-counts" class="secondary">見積用に枚数をコピー</button></div>
    <a class="text-link" href="/forms/template" target="_blank" rel="noopener noreferrer">この注文用に帳票ひな型をコピー ↗</a>`);
  $("#copy-counts").onclick = async () => {
    const text = quantities.join("\n");
    try {
      if (!navigator.clipboard?.writeText) throw new Error();
      await navigator.clipboard.writeText(text);
      message("半袖・長袖の順にコピーしました。見積書の半袖の点数欄に貼り付けてください。");
    } catch {
      const field = document.createElement("textarea");
      field.value = text;
      field.readOnly = true;
      field.setAttribute("aria-label", "見積用枚数（半袖、長袖の順）");
      $("#dialog-body").append(field);
      field.select();
      if (document.execCommand("copy")) {
        field.remove();
        message("半袖・長袖の順にコピーしました。");
      } else {
        message("表示された2行を選択した状態で、コピーしてください。");
      }
    }
  };
}

function countsBySleeve(items) {
  return ["SS", "LS"].map(prefix => sumQty(items.filter(item => item.code.startsWith(prefix))));
}

function changeTab(tab) {
  $$(".view").forEach(section => section.hidden = section.id !== tab);
  $$("[data-tab]").forEach(button => {
    if (button.dataset.tab === tab) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  });
  $("#notice").hidden = true;
  window.scrollTo(0, 0);
}

function changeEditMode(mode) {
  editMode = mode;
  const isNew = mode === "new";
  $$("[data-edit]").forEach(button => button.setAttribute("aria-pressed", button.dataset.edit === mode));
  $("#replace-field").hidden = isNew;
  $("#replace-code").required = !isNew;
  $("#new-fields").hidden = !isNew;
  $("#new-name").required = isNew;
  $("#update-product").textContent = isNew ? "新商品を登録" : "写真を差し替える";
  resetPhoto();
}

function resetPhoto() {
  $("#photo-file").value = "";
  $("#photo-preview").hidden = true;
  $("#photo-preview").removeAttribute("src");
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = "";
}

function readFile(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(new Error("選択した写真を読み込めませんでした。"));
    reader.readAsDataURL(file);
  });
}

$("#photo-file").onchange = () => {
  const file = $("#photo-file").files[0];
  if (previewURL) URL.revokeObjectURL(previewURL);
  previewURL = "";
  if (!file) { resetPhoto(); return; }
  if (!["image/jpeg", "image/png"].includes(file.type) || file.size > 12 * 1024 * 1024) {
    resetPhoto();
    message("12 MiB以下のJPEGまたはPNGを選択してください。", true);
    return;
  }
  previewURL = URL.createObjectURL(file);
  $("#photo-preview").src = previewURL;
  $("#photo-preview").hidden = false;
};
$("#product-form").onsubmit = event => {
  event.preventDefault();
  const file = $("#photo-file").files[0];
  if (!file) return;
  run(async () => {
    const fields = editMode === "new" ? {sleeve: $("#new-sleeve").value, name: $("#new-name").value.trim()}
      : {code: $("#replace-code").value};
    if (editMode === "new" && !fields.name) throw new Error("商品名を入力してください。");
    const previous = new Set(productsByCode.keys());
    const result = await api("/api/products", {...fields, image: await readFile(file)});
    resetPhoto();
    $("#new-name").value = "";
    await refresh();
    const code = fields.code || result.code || state.products.find(item => !previous.has(item.code))?.code;
    message((code || "商品") + " を保存しました。照合用一覧を再出力すると更新を反映できます。");
  });
};
$("#price-class-new").onsubmit = event => {
  event.preventDefault();
  const body = {label: $("#pc-new-label").value.trim(), unit_price: Number($("#pc-new-price").value)};
  run(async () => {
    await api("/api/price-classes", {...body, revision: state.revision});
    $("#pc-new-label").value = "";
    $("#pc-new-price").value = "";
    await refresh();
    message(PRICE_SAVED);
  });
};
$("#assign-code").onchange = syncAssignClass;
$("#price-assign-form").onsubmit = event => {
  event.preventDefault();
  const code = $("#assign-code").value;
  const priceClass = $("#assign-class").value || null;
  run(async () => {
    await api("/api/products/price-class", {code, price_class: priceClass, revision: state.revision});
    await refresh();
    $("#assign-code").value = code;
    syncAssignClass();
    message(code + " の単価区分を保存しました。確定済みの注文の単価は変わりません。");
  });
};
$("#export").onclick = () => run(async () => {
  await api("/api/export", {});
  message("照合用一覧を再出力しました。");
});

$$("[data-tab]").forEach(button => button.onclick = () => changeTab(button.dataset.tab));
$$("[data-edit]").forEach(button => button.onclick = () => changeEditMode(button.dataset.edit));
$$("[data-sleeve]").forEach(button => button.onclick = () => {
  sleeveFilter = button.dataset.sleeve;
  $$("[data-sleeve]").forEach(other => other.setAttribute("aria-pressed", other === button));
  renderCards();
});
$("#search").oninput = renderCards;
$("#cards").onclick = event => {
  const button = event.target.closest("[data-product]");
  if (button) showProduct(button.dataset.product);
};
$("#cart-lines").onclick = event => {
  const button = event.target.closest("[data-cart]");
  if (!button) return;
  const code = button.closest("[data-code]").dataset.code;
  const action = button.dataset.cart;
  if (action === "edit") { showProduct(code); return; }
  const qty = action === "remove" ? 0 : state.draft[code] + (action === "plus" ? 1 : -1);
  run(() => saveQty(code, qty));
};
$("#history-list").onclick = event => {
  const button = event.target.closest("[data-order]");
  if (button) run(() => showOrder(button.dataset.order));
};
$("#review").onclick = reviewDraft;
$("#close-dialog").onclick = () => dialog.close();
dialog.addEventListener("cancel", event => { if (busy) event.preventDefault(); });
run(refresh);
