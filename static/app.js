(() => {
const $ = (s, r = document) => r.querySelector(s), app = $('#app');
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const safe = u => /^https?:\/\//i.test(u || '') ? u : '#';
const ls = { get: (k, d) => { try { return JSON.parse(localStorage.getItem(k)) ?? d } catch { return d } }, set: (k, v) => { try { localStorage.setItem(k, JSON.stringify(v)) } catch {} } };
let token = ls.get('tok', null), user = null, saved = new Set(), cmp = ls.get('cmp', []);

async function api(path, o = {}) {
  const r = await fetch('/api/' + path, { method: o.method || 'GET', headers: { ...(o.body ? {'Content-Type':'application/json'} : {}), ...(token ? {Authorization: 'Bearer ' + token} : {}) }, body: o.body ? JSON.stringify(o.body) : undefined });
  const d = await r.json().catch(() => ({}));
  if (!r.ok) { if (r.status === 401 && token && path !== 'auth/login') signOutLocal(); throw new Error(d.error || 'Something went wrong. Try again.') }
  return d;
}
const money = (v, cur) => { try { return new Intl.NumberFormat(undefined, { style: 'currency', currency: cur || 'USD' }).format(v) } catch { return v + ' ' + (cur || '') } };
const priceText = p => p.price_min == null ? '<span class="na">Price not available</span>' : p.price_max > p.price_min ? `<span class="price">${money(p.price_min, p.currency)}–${money(p.price_max, p.currency)}</span>` : `<span class="price">${money(p.price_min, p.currency)}</span>`;
const rateText = p => p.rating == null ? '<span class="rate">No ratings available</span>' : `<span class="rate"><b>${(+p.rating).toFixed(1)}</b> ★ ${p.rating_count ? '(' + (+p.rating_count).toLocaleString() + ')' : ''}</span>`;
const toast = m => { const t = $('#toast'); t.textContent = m; t.classList.add('show'); clearTimeout(t._t); t._t = setTimeout(() => t.classList.remove('show'), 2400) };
const go = h => { location.hash = h };
const qs = o => new URLSearchParams(Object.entries(o).filter(([, v]) => v !== '' && v != null && v !== false)).toString();

function card(p) {
  const img = p.image_url ? `<img src="${esc(safe(p.image_url))}" alt="" loading="lazy" referrerpolicy="no-referrer">` : `<div class="ph" aria-hidden="true">${esc((p.name || '?')[0])}</div>`;
  const inC = cmp.some(c => c.id === p.id);
  return `<article class="card">${p.is_demo ? '<span class="demo">DEMO DATA</span>' : ''}
  <div class="acts"><button data-act="save" data-id="${p.id}" class="${saved.has(p.id) ? 'on' : ''}" aria-label="Save ${esc(p.name)}" title="Save to a wishlist">♥</button>
  <button data-act="cmp" data-id="${p.id}" data-name="${esc(p.name)}" class="${inC ? 'on' : ''}" aria-pressed="${inC}" aria-label="Compare ${esc(p.name)}" title="Add to comparison">⇄</button></div>
  <div class="img">${img}</div><div class="body"><a class="t" href="#/product/${p.id}">${esc(p.name)}</a>
  <span class="brand">${esc(p.brand || '')}</span>${priceText(p)}${rateText(p)}
  <span class="rate">${p.offer_count ? p.offer_count + ' seller' + (p.offer_count > 1 ? 's' : '') : 'No seller links yet'}</span></div></article>`;
}
const grid = (l, empty = 'Nothing here yet.') => l.length ? `<div class="grid">${l.map(card).join('')}</div>` : `<p class="note">${esc(empty)}</p>`;

function updateChrome() {
  $('#acct').textContent = user ? (user.name || 'Account') : 'Sign in';
  const b = $('#cmpCount'); b.hidden = !cmp.length; b.textContent = cmp.length;
}
function signOutLocal() { token = null; user = null; saved = new Set(); ls.set('tok', null); updateChrome() }
async function loadUser() {
  if (!token) return updateChrome();
  try { user = await api('me'); await refreshSaved() } catch { signOutLocal() }
  updateChrome();
}
async function refreshSaved() { const w = await api('wishlists'); saved = new Set(w.flatMap(x => x.items.map(i => i.id))); return w }

/* ---------- views ---------- */
async function home() {
  document.body.classList.add('home');
  app.innerHTML = `<section class="hero"><h1>Every product, one search.</h1><p>Search phones, sneakers, sofas, books and more. See who sells it, then go straight to the official store or a trusted retailer.</p>
  <form class="big" data-search role="search"><input type="search" name="q" id="hq" list="sg" placeholder="Search a product, brand or model" aria-label="Search a product, brand or model" autocomplete="off" autofocus><datalist id="sg"></datalist><button class="btn acc">Search</button></form><div class="chips" id="trend"></div></section><div id="homebody"><p class="na">Loading…</p></div>`;
  typePlaceholder();
  const d = await api('home');
  $('#trend').innerHTML = d.trending.length ? d.trending.map(t => `<a class="chip" href="#/search?q=${encodeURIComponent(t)}">${esc(t)}</a>`).join('') : '';
  const sec = (t, l) => l.length ? `<h2>${t}</h2>${grid(l)}` : '';
  $('#homebody').innerHTML = (d.total ? '' : `<div class="note"><b>The catalog is empty.</b> Search for anything and Shelfwise will look it up in connected data sources${d.providers.length ? ` (${esc(d.providers.join(', '))})` : ''}. You can also run <code>python ingest.py --crawl</code> or <code>python ingest.py --demo</code> to preview the layout.</div>`) +
    `<h2>Browse categories</h2><div class="cats">${d.categories.map(c => `<a class="cat" href="#/search?category=${encodeURIComponent(c.name)}"><span aria-hidden="true">${c.icon}</span><div>${esc(c.name)}<small>${c.count ? c.count.toLocaleString() + (c.count === 1 ? ' product' : ' products') : 'Expanding'}</small></div></a>`).join('')}</div>` +
    sec('Recommended for you', d.recommended) + sec('Popular products', d.popular) + sec('Top rated', d.featured) + sec('Recently added', d.recent);
}
let typer;
function typePlaceholder() {
  clearInterval(typer); const el = $('#hq'); if (!el || matchMedia('(prefers-reduced-motion:reduce)').matches) return;
  const ex = ['noise-cancelling headphones', 'running shoes', 'espresso machine', '4K monitor', 'children’s books', 'hiking backpack']; let i = 0, n = 0;
  typer = setInterval(() => { if (!document.body.contains(el) || el.value || document.activeElement === el && el.value) return; const w = ex[i]; n++; el.placeholder = w.slice(0, n) + '|'; if (n > w.length + 14) { n = 0; i = (i + 1) % ex.length } else if (n > w.length) el.placeholder = w }, 90);
}

async function search(q) {
  document.body.classList.remove('home');
  const p = { ...q }; const d = await api('search?' + qs(p));
  const link = o => '#/search?' + qs({ ...p, page: '', ...o });
  const title = p.q ? `Results for “${esc(p.q)}”` : p.category ? esc(p.category) : 'All products';
  app.innerHTML = `<div class="layout"><aside class="filters" aria-label="Filters">
   <div><h3>Category</h3><ul>${d.categories.slice(0, 12).map(c => `<li><a class="${p.category === c.name ? 'on' : ''}" href="${link({ category: p.category === c.name ? '' : c.name })}">${esc(c.name)} <span>${c.n}</span></a></li>`).join('') || '<li class="na">None</li>'}</ul></div>
   <div><h3>Brand</h3><ul>${d.brands.map(c => `<li><a class="${p.brand === c.name ? 'on' : ''}" href="${link({ brand: p.brand === c.name ? '' : c.name })}">${esc(c.name)} <span>${c.n}</span></a></li>`).join('') || '<li class="na">None</li>'}</ul></div>
   <form data-filter><h3>Price</h3><div class="row"><input type="number" min="0" name="min" placeholder="Min" value="${esc(p.min || '')}" aria-label="Minimum price"><input type="number" min="0" name="max" placeholder="Max" value="${esc(p.max || '')}" aria-label="Maximum price"></div><br>
   <h3>Rating</h3><select name="rating" aria-label="Minimum rating">${['', 4, 3, 2].map(v => `<option value="${v}" ${String(p.rating || '') === String(v) ? 'selected' : ''}>${v ? v + '★ & up' : 'Any rating'}</option>`).join('')}</select><br><br>
   <label><input type="checkbox" name="available" value="1" ${p.available ? 'checked' : ''}> In stock at a seller</label><br><button class="btn sm">Apply</button></form></aside>
   <section><div class="head"><div><h1 style="font:600 30px var(--serif);margin:0">${title}</h1><span class="na">${d.total.toLocaleString()} product${d.total === 1 ? '' : 's'}</span></div>
   <label class="sort">Sort <select data-sort aria-label="Sort results">${[['', 'Relevance'], ['popularity', 'Popularity'], ['rating', 'Rating'], ['price_asc', 'Price: low to high'], ['price_desc', 'Price: high to low']].map(([v, t]) => `<option value="${v}" ${(p.sort || '') === v ? 'selected' : ''}>${t}</option>`).join('')}</select></label></div>
   ${d.discovering ? '<div class="note" id="disc">Looking for more matches in our data sources… results will refresh automatically.</div>' : ''}
   ${grid(d.items, p.q ? 'No matching products yet. We check connected data sources for new queries, so try again in a moment or search a broader term.' : 'No products match these filters.')}
   ${d.pages > 1 ? `<nav class="pager" aria-label="Pages">${d.page > 1 ? `<a class="btn ghost sm" href="${link({ page: d.page - 1 })}">Previous</a>` : ''}<span class="na">Page ${d.page} of ${d.pages}</span>${d.page < d.pages ? `<a class="btn ghost sm" href="${link({ page: d.page + 1 })}">Next</a>` : ''}</nav>` : ''}</section></div>`;
  if (d.discovering) { const key = location.hash; let n = 0; const t = setInterval(async () => { if (location.hash !== key || ++n > 3) return clearInterval(t); const r = await api('search?' + qs({ ...p, page: p.page })); if (r.total > d.total) { clearInterval(t); render() } }, 5000) }
}

async function product(id) {
  document.body.classList.remove('home');
  const p = await api('product/' + id);
  const inC = cmp.some(c => c.id === p.id);
  const sp = Object.entries(p.specs || {});
  const buy = p.offers.length ? `<div class="sellers">${p.offers.map(o => `<div class="seller"><div class="n"><b>${esc(o.seller)}</b> ${o.is_official ? '<span class="tag off">Official</span>' : ''}<small>${o.price != null ? money(o.price, o.currency) : 'Price not available'} · <span class="${o.availability === 'in_stock' ? 'in' : o.availability === 'out_of_stock' ? 'out' : ''}">${{ in_stock: 'In stock', out_of_stock: 'Out of stock', unknown: 'Availability unknown' }[o.availability] || 'Availability unknown'}</span></small></div>
    <a class="btn sm" href="${esc(safe(o.url))}" target="_blank" rel="noopener noreferrer nofollow sponsored">View at ${esc(o.seller)}</a></div>`).join('')}</div>` : '<p class="note">No direct seller listing for this product is available from our data sources yet. Use the search links below.</p>';
  app.innerHTML = `<p><a href="javascript:history.back()">← Back</a></p><div class="prod"><div class="gallery">${p.image_url ? `<img src="${esc(safe(p.image_url))}" alt="${esc(p.name)}" referrerpolicy="no-referrer">` : '<div class="ph">' + esc(p.name[0]) + '</div>'}</div>
  <div><a class="chip" href="#/search?category=${encodeURIComponent(p.category || '')}">${esc(p.category || 'Uncategorized')}</a> ${p.is_demo ? '<span class="tag">Demo data</span>' : ''}
  <h1>${esc(p.name)}</h1><div class="brand">${p.brand ? 'By <a href="#/search?brand=' + encodeURIComponent(p.brand) + '">' + esc(p.brand) + '</a>' : 'Brand not available'}${p.model ? ' · Model ' + esc(p.model) : ''}</div>
  <div class="big-price">${priceText(p)}</div><div>${rateText(p)} <span class="na">· Written reviews aren’t available from our sources.</span></div>
  <div class="row" style="margin:16px 0"><button class="btn ghost sm" data-act="save" data-id="${p.id}">${saved.has(p.id) ? '♥ Saved' : '♡ Save'}</button><button class="btn ghost sm" data-act="cmp" data-id="${p.id}" data-name="${esc(p.name)}">${inC ? '✓ In comparison' : '⇄ Compare'}</button></div>
  ${p.official_url ? `<p><a class="btn acc" href="${esc(safe(p.official_url))}" target="_blank" rel="noopener noreferrer">Official website</a></p>` : ''}
  <h2 style="margin-top:20px">Where to buy</h2>${buy}
  <h3 style="margin-top:20px">Search for this product at</h3><div class="chips" style="margin-top:6px">${p.search_links.map(l => `<a class="chip" href="${esc(safe(l.url))}" target="_blank" rel="noopener noreferrer nofollow">${esc(l.seller)}</a>`).join('')}</div>
  <p class="na">These open a search for this product, not a confirmed listing. Prices shown above come from the listed provider only.</p></div></div>
  <h2>About this product</h2><p style="max-width:70ch">${p.description ? esc(p.description) : '<span class="na">Description not available from our data sources.</span>'}</p>
  ${(p.features || []).length ? `<h2>Features</h2><ul>${p.features.map(f => `<li>${esc(f)}</li>`).join('')}</ul>` : ''}
  <h2>Specifications</h2>${sp.length ? `<div class="scroll"><table>${sp.map(([k, v]) => `<tr><th scope="row">${esc(k)}</th><td>${esc(v)}</td></tr>`).join('')}</table></div>` : '<p class="na">Specifications not available from our data sources.</p>'}
  <h2>Pros and cons</h2>${p.pros.length || p.cons.length ? `<div class="two"><div class="pros"><h3>Pros</h3><ul>${p.pros.map(x => `<li>${esc(x)}</li>`).join('') || '<li class="na">None listed</li>'}</ul></div><div class="cons"><h3>Cons</h3><ul>${p.cons.map(x => `<li>${esc(x)}</li>`).join('') || '<li class="na">None listed</li>'}</ul></div></div>` : '<p class="na">Pros and cons are only shown when a data source provides facts to base them on. None are available for this product.</p>'}
  <div id="vids"></div>
  ${p.similar.length ? `<h2>Similar products</h2>${grid(p.similar)}` : ''}
  <p class="na" style="margin-top:36px">Source: ${esc(p.attribution || 'Not specified')} ${p.license ? '· License: ' + esc(p.license) : ''}</p>`;
  document.title = p.name + ' · Shelfwise';
  loadVideos(id);
}

async function loadVideos(id) {
  try {
    const v = await api('video/' + id), el = $('#vids'); if (!el) return;
    el.innerHTML = '<h2>Videos</h2>' + (v.videos.length ? `<div class="grid">${v.videos.map(x => `<a class="card vid" href="https://www.youtube.com/watch?v=${encodeURIComponent(x.id)}" target="_blank" rel="noopener noreferrer"><div class="img"><img src="${esc(safe(x.thumb))}" alt="" loading="lazy" referrerpolicy="no-referrer"></div><div class="body"><b>${esc(x.title)}</b><span class="brand">${esc(x.channel)} · YouTube</span></div></a>`).join('')}</div>` : '') +
      `<p class="na">${v.videos.length ? 'Search for more:' : 'Find videos about this product. These open a search, not a specific video:'}</p><div class="chips">${v.links.map(l => `<a class="chip" href="${esc(safe(l.url))}" target="_blank" rel="noopener noreferrer nofollow">${esc(l.site)}</a>`).join('')}</div>`;
  } catch {}
}

async function compare(q) {
  document.body.classList.remove('home');
  const ids = (q.ids ? q.ids.split(',').map(Number) : cmp.map(c => c.id)).slice(0, 4);
  if (ids.length < 1) return app.innerHTML = `<h2>Compare products</h2><p class="note">Pick products with the ⇄ button on any card, then come back here. You can compare up to four.</p>`;
  const L = await api('compare?ids=' + ids.join(','));
  const keys = [...new Set(L.flatMap(p => Object.keys(p.specs || {})))];
  const lows = L.map(p => p.price_min).filter(v => v != null), low = lows.length ? Math.min(...lows) : null;
  const row = (label, f, raw) => { const cells = L.map(f); const diff = new Set(cells.map(c => String(raw ? raw : c))).size > 1; return `<tr class="${diff ? 'diff' : ''}"><th scope="row">${label}</th>${cells.map(c => `<td>${c}</td>`).join('')}</tr>` };
  const na = '<span class="na">Not available</span>';
  app.innerHTML = `<div class="head"><h1 style="font:600 34px var(--serif)">Compare</h1><div class="row"><button class="btn ghost sm" data-act="clearcmp">Clear</button>${user ? '<button class="btn sm" data-act="savecmp">Save comparison</button>' : '<a class="btn ghost sm" href="#/account">Sign in to save</a>'}</div></div>
  <p class="na">Rows with differences are highlighted.</p><div class="scroll"><table class="cmp"><tr><th></th>${L.map(p => `<td><a href="#/product/${p.id}"><b>${esc(p.name)}</b></a><br><button class="btn ghost sm" data-act="cmp" data-id="${p.id}" data-name="">Remove</button></td>`).join('')}</tr>
  ${row('Image', p => p.image_url ? `<img src="${esc(safe(p.image_url))}" alt="" width="110" style="background:#fff;border-radius:8px" referrerpolicy="no-referrer">` : na, 'x')}
  ${row('Brand', p => esc(p.brand) || na)}${row('Category', p => esc(p.category) || na)}
  ${row('Price', p => (p.price_min == null ? na : priceText(p)) + (low != null && p.price_min === low && lows.length > 1 ? ' <span class="tag off">Lowest</span>' : ''), '')}
  ${row('Rating', p => p.rating == null ? na : rateText(p))}
  ${row('Sellers', p => p.offers.length ? p.offers.map(o => `<a href="${esc(safe(o.url))}" target="_blank" rel="noopener noreferrer nofollow sponsored">${esc(o.seller)}</a>${o.price != null ? ' ' + money(o.price, o.currency) : ''}`).join('<br>') : na)}
  ${keys.map(k => row(esc(k), p => (p.specs || {})[k] != null ? esc(p.specs[k]) : na)).join('')}
  ${row('Features', p => (p.features || []).length ? '<ul style="margin:0;padding-left:16px">' + p.features.slice(0, 6).map(f => `<li>${esc(f)}</li>`).join('') + '</ul>' : na)}</table></div>`;
}

async function account(q, tab) {
  document.body.classList.remove('home');
  if (!user) {
    const reg = q.mode === 'register';
    app.innerHTML = `<div class="form" style="margin-top:36px"><h1 style="font:600 34px var(--serif);margin:0">${reg ? 'Create your account' : 'Sign in'}</h1><p class="na">Optional. You can search, browse and compare without an account. An account lets you save products, make wishlists and keep your history.</p>
    <form class="form" data-auth="${reg ? 'register' : 'login'}">${reg ? '<input name="name" placeholder="Name (optional)" autocomplete="name">' : ''}<input name="email" type="email" placeholder="Email" required autocomplete="email"><input name="password" type="password" placeholder="Password (8+ characters)" required minlength="${reg ? 8 : 1}" autocomplete="${reg ? 'new-password' : 'current-password'}"><div class="err" role="alert"></div><button class="btn">${reg ? 'Create account' : 'Sign in'}</button></form>
    <a href="#/account?mode=${reg ? 'login' : 'register'}">${reg ? 'I already have an account' : 'Create an account'}</a><a href="#/">Continue as guest</a></div>`; return;
  }
  tab = tab || 'wishlists';
  const tabs = [['wishlists', 'Wishlists'], ['recent', 'Recent'], ['comparisons', 'Saved comparisons'], ['settings', 'Settings']];
  let body = '';
  if (tab === 'wishlists') { const w = await refreshSaved(); body = `<form class="row" data-newlist><input name="name" placeholder="New wishlist name" required maxlength="60" style="padding:9px 12px;border:1px solid var(--line);border-radius:8px;background:var(--surf)"><button class="btn sm">Create list</button></form>` + w.map(l => `<h2>${esc(l.name)} <small class="na">${l.items.length}</small> ${l.name !== 'Favorites' ? `<button class="btn ghost sm" data-act="dellist" data-id="${l.id}">Delete list</button>` : ''}</h2>${grid(l.items, 'Nothing saved here yet. Tap ♥ on any product.')}`).join('') }
  if (tab === 'recent') { const h = await api('history'); body = `<div class="row"><h2 class="sp">Recent searches</h2><button class="btn ghost sm" data-act="clearhist">Clear history</button></div><div class="chips">${h.filter(x => x.kind === 'search').map(x => `<a class="chip" href="#/search?q=${encodeURIComponent(x.label)}">${esc(x.label)}</a>`).join('') || '<span class="na">No searches yet.</span>'}</div><h2>Recently viewed</h2><div class="chips">${h.filter(x => x.kind === 'product').map(x => `<a class="chip" href="#/product/${esc(x.ref)}">${esc(x.label)}</a>`).join('') || '<span class="na">No products viewed yet.</span>'}</div>` }
  if (tab === 'comparisons') { const c = await api('comparisons'); body = c.length ? c.map(x => `<div class="seller"><div class="n"><b>${esc(x.name)}</b><small>${x.product_ids.length} products</small></div><a class="btn sm" href="#/compare?ids=${x.product_ids.join(',')}">Open</a><button class="btn ghost sm" data-act="delcmp" data-id="${x.id}">Delete</button></div>`).join('') : '<p class="note">No saved comparisons. Compare products, then choose “Save comparison”.</p>' }
  if (tab === 'settings') body = `<div class="form"><p>Signed in as <b>${esc(user.email)}</b></p><form class="form" data-settings><input name="name" value="${esc(user.name || '')}" placeholder="Display name" maxlength="60"><input name="current_password" type="password" placeholder="Current password (to change it)" autocomplete="current-password"><input name="new_password" type="password" placeholder="New password (8+ characters)" autocomplete="new-password"><div class="err" role="alert"></div><button class="btn">Save changes</button></form><button class="btn ghost" data-act="logout">Sign out</button><button class="btn ghost" data-act="delacct" style="color:var(--bad)">Delete account</button></div>`;
  app.innerHTML = `<h1 style="font:600 34px var(--serif);margin:24px 0 0">Your account</h1><div class="tabs" role="tablist">${tabs.map(([k, t]) => `<a class="${k === tab ? 'on' : ''}" href="#/account?tab=${k}">${t}</a>`).join('')}</div>${body}`;
}

function categories() {
  document.body.classList.remove('home');
  return api('home').then(d => app.innerHTML = `<h2 style="margin-top:28px">All categories</h2><div class="cats">${d.categories.map(c => `<a class="cat" href="#/search?category=${encodeURIComponent(c.name)}"><span aria-hidden="true">${c.icon}</span><div>${esc(c.name)}<small>${c.count ? c.count.toLocaleString() + (c.count === 1 ? ' product' : ' products') : 'Expanding'}</small></div></a>`).join('')}</div>`);
}

/* ---------- router ---------- */
async function render() {
  const h = location.hash.slice(1) || '/', [path, s] = h.split('?'), q = Object.fromEntries(new URLSearchParams(s || '')), seg = path.split('/').filter(Boolean);
  document.title = 'Shelfwise · Find any product, buy from the source';
  try {
    app.setAttribute('aria-busy', 'true');
    if (!seg.length) await home();
    else if (seg[0] === 'search') await search(q);
    else if (seg[0] === 'product') await product(+seg[1]);
    else if (seg[0] === 'compare') await compare(q);
    else if (seg[0] === 'account') await account(q, q.tab);
    else if (seg[0] === 'categories') await categories();
    else app.innerHTML = '<p class="note">Page not found. <a href="#/">Go home</a></p>';
  } catch (e) { app.innerHTML = `<p class="note" role="alert">${esc(e.message)} <a href="#/">Go home</a></p>` }
  app.removeAttribute('aria-busy'); if (seg.length) window.scrollTo(0, 0);
}

/* ---------- events ---------- */
async function pickList(pid) {
  if (!user) { toast('Sign in to save products'); return go('#/account') }
  const w = await refreshSaved(), m = $('#modal');
  const draw = (ws) => { m.innerHTML = `<div role="dialog" aria-modal="true" aria-label="Save to wishlist"><h3>Save to a wishlist</h3>${ws.map(l => `<label class="row" style="padding:6px 0"><input type="checkbox" data-wl="${l.id}" ${l.items.some(i => i.id === pid) ? 'checked' : ''}> ${esc(l.name)}</label>`).join('')}<form class="row" data-modalnew style="margin-top:12px"><input name="name" placeholder="New list" maxlength="60" style="flex:1;padding:8px;border:1px solid var(--line);border-radius:8px;background:var(--surf)"><button class="btn sm">Add</button></form><p><button class="btn ghost sm" data-act="closemodal">Done</button></p></div>`; m.hidden = false; m._pid = pid; m._ws = ws; $('input,button', m).focus() };
  draw(w);
}
document.addEventListener('submit', async e => {
  const f = e.target; if (!(f instanceof HTMLFormElement)) return;
  const fd = Object.fromEntries(new FormData(f));
  if (f.hasAttribute('data-search')) { e.preventDefault(); if ((fd.q || '').trim()) go('#/search?' + qs({ q: fd.q.trim() })); }
  else if (f.hasAttribute('data-filter')) { e.preventDefault(); const cur = Object.fromEntries(new URLSearchParams((location.hash.split('?')[1]) || '')); delete cur.page; go('#/search?' + qs({ ...cur, min: fd.min, max: fd.max, rating: fd.rating, available: fd.available })) }
  else if (f.dataset.auth) { e.preventDefault(); const er = $('.err', f); er.textContent = ''; try { const r = await api('auth/' + f.dataset.auth, { method: 'POST', body: fd }); token = r.token; ls.set('tok', token); user = r.user; await refreshSaved(); updateChrome(); toast('Welcome, ' + (user.name || 'there')); go('#/account') } catch (x) { er.textContent = x.message } }
  else if (f.hasAttribute('data-newlist')) { e.preventDefault(); try { await api('wishlists', { method: 'POST', body: fd }); render() } catch (x) { toast(x.message) } }
  else if (f.hasAttribute('data-modalnew')) { e.preventDefault(); if (!fd.name.trim()) return; const n = await api('wishlists', { method: 'POST', body: fd }); await api(`wishlists/${n.id}/items`, { method: 'POST', body: { product_id: $('#modal')._pid } }); await refreshSaved(); toast('Saved to ' + n.name); $('#modal').hidden = true; render() }
  else if (f.hasAttribute('data-settings')) { e.preventDefault(); const er = $('.err', f); try { user = await api('me', { method: 'PATCH', body: fd }); updateChrome(); er.textContent = ''; toast('Saved') } catch (x) { er.textContent = x.message } }
});
document.addEventListener('change', async e => {
  const t = e.target;
  if (t.matches('[data-sort]')) { const cur = Object.fromEntries(new URLSearchParams((location.hash.split('?')[1]) || '')); delete cur.page; go('#/search?' + qs({ ...cur, sort: t.value })) }
  if (t.dataset.wl) { const pid = $('#modal')._pid; try { await api(`wishlists/${t.dataset.wl}/items${t.checked ? '' : '/' + pid}`, { method: t.checked ? 'POST' : 'DELETE', body: t.checked ? { product_id: pid } : undefined }); await refreshSaved(); document.querySelectorAll(`[data-act=save][data-id="${pid}"]`).forEach(b => b.classList.toggle('on', saved.has(pid))) } catch (x) { toast(x.message) } }
});
document.addEventListener('input', e => { const t = e.target; if (t.id === 'hq' && t.value.length > 1) { clearTimeout(t._d); t._d = setTimeout(async () => { try { const r = await api('suggest?q=' + encodeURIComponent(t.value)); $('#sg').innerHTML = r.map(n => `<option value="${esc(n)}">`).join('') } catch {} }, 200) } });
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-act]'); if (!b) { if (e.target.id === 'modal') e.target.hidden = true; return }
  const id = +b.dataset.id, act = b.dataset.act;
  try {
    if (act === 'theme') { const t = document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'; document.documentElement.dataset.theme = t; try { localStorage.setItem('theme', t) } catch {} }
    else if (act === 'save') pickList(id);
    else if (act === 'closemodal') { $('#modal').hidden = true; render() }
    else if (act === 'cmp') { const i = cmp.findIndex(c => c.id === id); if (i >= 0) cmp.splice(i, 1); else if (cmp.length >= 4) return toast('You can compare up to 4 products'); else cmp.push({ id, name: b.dataset.name }); ls.set('cmp', cmp); updateChrome(); if (location.hash.startsWith('#/compare')) render(); else { b.classList.toggle('on'); if (b.classList.contains('btn')) b.textContent = i >= 0 ? '⇄ Compare' : '✓ In comparison'; toast(i >= 0 ? 'Removed from comparison' : `Added to comparison (${cmp.length})`) } }
    else if (act === 'clearcmp') { cmp = []; ls.set('cmp', cmp); updateChrome(); render() }
    else if (act === 'savecmp') { const ids = (new URLSearchParams(location.hash.split('?')[1] || '').get('ids') || cmp.map(c => c.id).join(',')).split(',').map(Number); if (ids.length < 2) return toast('Add at least two products first'); await api('comparisons', { method: 'POST', body: { name: 'Comparison ' + new Date().toLocaleDateString(), product_ids: ids } }); toast('Comparison saved') }
    else if (act === 'logout') { await api('auth/logout', { method: 'POST' }).catch(() => {}); signOutLocal(); go('#/') }
    else if (act === 'delcmp') { await api('comparisons/' + id, { method: 'DELETE' }); render() }
    else if (act === 'dellist') { if (confirm('Delete this wishlist?')) { await api('wishlists/' + id, { method: 'DELETE' }); render() } }
    else if (act === 'clearhist') { await api('history', { method: 'DELETE' }); render() }
    else if (act === 'delacct') { const pw = prompt('Enter your password to permanently delete your account:'); if (pw) { await api('me', { method: 'DELETE', body: { password: pw } }); signOutLocal(); toast('Account deleted'); go('#/') } }
  } catch (x) { toast(x.message) }
});
document.addEventListener('keydown', e => { if (e.key === 'Escape') $('#modal').hidden = true });
window.addEventListener('hashchange', render);
loadUser().then(render);
})();
