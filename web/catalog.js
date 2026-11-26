/* Global model catalog: rendering only, data comes from model_catalog.py */
const catalogState = {models: [], filtered: [], page: 1, view: "cards", loading: false, loaded: false};
const catalogMetric = (v, suffix = "", digits = 1) => v == null || Number.isNaN(Number(v)) ? "—" : Number(v).toFixed(digits).replace(/\.0$/, "") + suffix;
const catalogPercent = v => {
  if (v == null) return "—";
  const n = Number(v);
  return (n <= 1 ? n * 100 : n).toFixed(1).replace(/\.0$/, "") + "%";
};
const catalogMoney = v => {
  if (v == null) return "—";
  const n = Number(v);
  if (n === 0) return "$0";
  if (n < 0.001) return "$" + n.toFixed(5);
  if (n < 0.01) return "$" + n.toFixed(4);
  if (n < 0.1) return "$" + n.toFixed(3);
  return "$" + n.toFixed(2).replace(/\.00$/, "");
};
const catalogContext = v => {
  if (!v) return "—";
  if (v >= 1000000) return (v / 1000000).toFixed(v % 1000000 ? 2 : 0).replace(/\.00$/, "") + "M";
  if (v >= 1000) return Math.round(v / 1000) + "K";
  return String(v);
};
const catalogCost = m => {
  const c = m.cost || {}, b = m.benchmarks || {};
  return `${catalogMoney(b.aa_price_input ?? c.input)} / ${catalogMoney(b.aa_price_output ?? c.output)}`;
};
const catalogOwn = m => m.own?.summary?.TOTAL == null ? "—" : Math.round(m.own.summary.TOTAL);

async function refreshCatalog(force = false) {
  if (catalogState.loading || (catalogState.loaded && !force)) return;
  catalogState.loading = true;
  $("#modelsLoading").classList.remove("hide");
  $("#modelsRefresh").disabled = true;
  $("#modelsRefreshMsg").textContent = force ? "Обновляю Models.dev, Artificial Analysis и LMArena…" : "Загружаю каталог…";
  try {
    const data = force
      ? await api("/api/catalog/refresh", {aa_key: $("#aaKey").value.trim()})
      : await api("/api/catalog");
    catalogState.models = data.models || [];
    catalogState.loaded = true;
    if (!catalogState.models.some(m => m.benchmarks?.aa_intelligence != null) && $("#modelSort").value === "intelligence") {
      $("#modelSort").value = "newest";
    }
    catalogState.page = 1;
    renderCatalogMeta(data);
    fillCatalogLabs();
    renderCatalog();
    const errors = data.errors || [];
    $("#modelsRefreshMsg").textContent = errors.length
      ? `Обновлено с предупреждениями: ${errors.join(" · ")}`
      : `Готово: ${catalogState.models.length} моделей, кеш сохранён локально`;
  } catch (e) {
    $("#modelsRefreshMsg").textContent = "Не удалось обновить каталог. Проверьте интернет и локальный сервер.";
  } finally {
    catalogState.loading = false;
    $("#modelsLoading").classList.add("hide");
    $("#modelsRefresh").disabled = false;
  }
}

function renderCatalogMeta(data) {
  const models = catalogState.models;
  $("#modelsTotal").textContent = fmt(models.length);
  $("#modelsMeasured").textContent = fmt(models.filter(m => m.benchmarks?.aa_intelligence != null).length);
  $("#modelsCountries").textContent = fmt(new Set(models.map(m => m.country).filter(c => c && c !== "other")).size);
  const s = data.sources || {}, dates = [];
  if (s.models_dev_date) dates.push("Models.dev: " + s.models_dev_date.slice(0, 10));
  if (s.aa_date) dates.push("AA " + (s.aa_tier || "") + ": " + s.aa_date.slice(0, 10));
  $("#modelsDates").textContent = dates.length ? "· обновлено " + dates.join(" · ") : "· офлайн-кеш";
}

function fillCatalogLabs() {
  const select = $("#modelLab"), current = select.value;
  const labs = [...new Set(catalogState.models.map(m => m.lab).filter(Boolean))].sort((a, b) => a.localeCompare(b));
  select.innerHTML = `<option value="">Все провайдеры</option>` + labs.map(x => `<option value="${esc(x)}">${esc(x)}</option>`).join("");
  select.value = labs.includes(current) ? current : "";
}

function catalogFiltered() {
  const q = $("#modelSearch").value.trim().toLowerCase(), region = $("#modelRegion").value,
        lab = $("#modelLab").value, open = $("#modelOpen").value, sort = $("#modelSort").value;
  const mainRegions = ["США", "Китай", "Россия", "Европа"];
  const list = catalogState.models.filter(m => {
    const hay = `${m.name} ${m.id} ${m.lab} ${m.provider_name} ${m.description}`.toLowerCase();
    if (q && !hay.includes(q)) return false;
    if (region && (region === "Другие" ? mainRegions.includes(m.region) : m.region !== region)) return false;
    if (lab && m.lab !== lab) return false;
    if (open === "open" && !m.open_weights) return false;
    if (open === "closed" && m.open_weights) return false;
    return true;
  });
  const nullLast = (v, direction = 1) => v == null ? direction * 1e100 : direction * Number(v);
  const price = m => (m.benchmarks?.aa_price_input ?? m.cost?.input ?? 1e50) + (m.benchmarks?.aa_price_output ?? m.cost?.output ?? 0);
  const comparators = {
    intelligence: (a, b) => nullLast(b.benchmarks?.aa_intelligence, -1) - nullLast(a.benchmarks?.aa_intelligence, -1),
    arena: (a, b) => nullLast(b.benchmarks?.arena, -1) - nullLast(a.benchmarks?.arena, -1),
    newest: (a, b) => String(b.release_date || b.last_updated || "").localeCompare(String(a.release_date || a.last_updated || "")),
    priceAsc: (a, b) => price(a) - price(b),
    priceDesc: (a, b) => price(b) - price(a),
    context: (a, b) => (b.context || 0) - (a.context || 0),
    speed: (a, b) => nullLast(b.benchmarks?.aa_speed, -1) - nullLast(a.benchmarks?.aa_speed, -1),
    own: (a, b) => (b.own ? 1 : 0) - (a.own ? 1 : 0) || (b.own?.summary?.TOTAL ?? -1) - (a.own?.summary?.TOTAL ?? -1),
    name: (a, b) => a.name.localeCompare(b.name),
    gpqa: (a, b) => nullLast(b.benchmarks?.gpqa, -1) - nullLast(a.benchmarks?.gpqa, -1),
    hle: (a, b) => nullLast(b.benchmarks?.hle, -1) - nullLast(a.benchmarks?.hle, -1),
    lcb: (a, b) => nullLast(b.benchmarks?.lcb, -1) - nullLast(a.benchmarks?.lcb, -1),
    region: (a, b) => String(a.region).localeCompare(String(b.region)) || a.name.localeCompare(b.name),
  };
  list.sort(comparators[sort] || comparators.intelligence);
  return list;
}

function renderCatalog() {
  catalogState.filtered = catalogFiltered();
  const pageSize = catalogState.view === "cards" ? 24 : 50,
        pages = Math.max(1, Math.ceil(catalogState.filtered.length / pageSize));
  catalogState.page = Math.min(catalogState.page, pages);
  const start = (catalogState.page - 1) * pageSize,
        visible = catalogState.filtered.slice(start, start + pageSize);
  $("#modelsCount").textContent = catalogState.filtered.length
    ? `Показано ${fmt(start + 1)}–${fmt(start + visible.length)} из ${fmt(catalogState.filtered.length)} · всего ${fmt(catalogState.models.length)}`
    : "Ничего не найдено — измените поиск или фильтры";
  $("#modelsPage").textContent = `${catalogState.page} / ${pages}`;
  $("#modelsPrev").disabled = catalogState.page <= 1;
  $("#modelsNext").disabled = catalogState.page >= pages;
  $("#modelsPagination").classList.toggle("hide", !catalogState.filtered.length);
  $("#modelCards").classList.toggle("hide", catalogState.view !== "cards");
  $("#modelsTableWrap").classList.toggle("hide", catalogState.view !== "table");
  if (catalogState.view === "cards") renderCatalogCards(visible);
  else renderCatalogTable(visible);
}

function renderCatalogCards(models) {
  if (!models.length) { $("#modelCards").innerHTML = `<div class="models-empty">Модели не найдены</div>`; return; }
  $("#modelCards").innerHTML = models.map(m => {
    const b = m.benchmarks || {}, score = b.aa_intelligence;
    return `<article class="model-card" data-model-id="${esc(m.id)}" tabindex="0" role="button" aria-label="Открыть ${esc(m.name)}">
      <div class="model-card-top"><div><h3>${esc(m.name)}</h3><div class="model-lab">${esc(m.lab)} · ${m.providers.length} провайдеров</div></div></div>
      <div class="model-badges"><span class="model-badge country">${esc(m.country_name || m.region)}</span>${m.open_weights ? '<span class="model-badge open">OPEN</span>' : '<span class="model-badge">PROPRIETARY</span>'}${m.reasoning ? '<span class="model-badge reason">REASONING</span>' : ""}</div>
      <div class="model-score"><div class="model-score-main"><b>${catalogMetric(score)}</b><span>AA INDEX</span></div><div class="model-score-side">Arena<br><b>${b.arena == null ? "—" : Math.round(b.arena)}</b></div></div>
      <div class="model-mini-metrics">
        <div class="model-mini"><span>GPQA</span><b>${catalogPercent(b.gpqa)}</b></div>
        <div class="model-mini"><span>HLE</span><b>${catalogPercent(b.hle)}</b></div>
        <div class="model-mini"><span>Code</span><b>${catalogPercent(b.lcb)}</b></div>
        <div class="model-mini"><span>Контекст</span><b>${catalogContext(m.context)}</b></div>
        <div class="model-mini"><span>Ток/с</span><b>${catalogMetric(b.aa_speed, "", 1)}</b></div>
        <div class="model-mini"><span>Цена in/out</span><b>${catalogCost(m)}</b></div>
        <div class="model-mini model-own"><span>Мой LLM Bench</span><b>${catalogOwn(m)}</b></div>
      </div>
      <div class="model-card-foot"><span>${esc(m.release_date || m.last_updated || "дата не указана")}</span><span>${m.context ? catalogContext(m.context) + " tokens" : "подробнее →"}</span></div>
    </article>`;
  }).join("");
  $$(".model-card").forEach(card => {
    card.onclick = () => openModelDetail(card.dataset.modelId);
    card.onkeydown = e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openModelDetail(card.dataset.modelId); } };
  });
}

function renderCatalogTable(models) {
  $("#modelsTableBody").innerHTML = models.map(m => {
    const b = m.benchmarks || {};
    return `<tr data-model-id="${esc(m.id)}"><td><span class="table-model-name">${esc(m.name)}</span><span class="table-model-lab">${esc(m.lab)}</span></td>
      <td>${esc(m.region)}</td><td>${catalogMetric(b.aa_intelligence)}</td><td>${catalogPercent(b.gpqa)}</td><td>${catalogPercent(b.hle)}</td>
      <td>${catalogPercent(b.lcb)}</td><td>${b.arena == null ? "—" : Math.round(b.arena)}</td><td>${catalogMetric(b.aa_speed)}</td>
      <td>${catalogCost(m)}</td><td>${catalogContext(m.context)}</td><td>${catalogOwn(m)}</td></tr>`;
  }).join("");
  $$("#modelsTableBody tr").forEach(row => row.onclick = () => openModelDetail(row.dataset.modelId));
}

function openModelDetail(id) {
  const m = catalogState.models.find(x => x.id === id);
  if (!m) return;
  const b = m.benchmarks || {}, own = m.own;
  const metrics = [
    ["AA Intelligence", catalogMetric(b.aa_intelligence)], ["GPQA Diamond", catalogPercent(b.gpqa)],
    ["HLE", catalogPercent(b.hle)], ["Code / SciCode", catalogPercent(b.lcb)],
    ["FrontierCode", catalogPercent(b.frontier_code)], ["Terminal-Bench", catalogPercent(b.terminal_bench)],
    ["Arena Elo", b.arena == null ? "—" : Math.round(b.arena)], ["Ранг Arena", b.arena_rank ? "#" + b.arena_rank : "—"],
    ["Скорость", catalogMetric(b.aa_speed, " ток/с")], ["Первый ответ", catalogMetric(b.aa_first_answer, " с")],
    ["Engineering", catalogMetric(b.aa_engineering)], ["Economics", catalogMetric(b.aa_economics)],
    ["Finance", catalogMetric(b.aa_finance)], ["Strategy & Ops", catalogMetric(b.aa_strategy)],
    ["Legal", catalogMetric(b.aa_legal)], ["Healthcare", catalogMetric(b.aa_healthcare)],
  ];
  const ownMetrics = own ? `<div class="model-detail-section"><h3>Мой LLM Bench · ${esc(own.date || "")}</h3><div class="model-detail-grid">` +
    Object.entries(own.summary || {}).map(([k, v]) => `<div class="model-detail-metric"><span>${esc(k)}</span><b>${catalogMetric(v)}</b></div>`).join("") +
    `</div><div class="hint">Запросов: ${fmt(own.tokens?.requests)} · вход: ${fmt(own.tokens?.in)} · выход: ${fmt(own.tokens?.out)}</div></div>` : "";
  $("#modelDetailContent").innerHTML = `
    <div class="model-detail-head"><h2>${esc(m.name)}</h2><p>${esc(m.lab)} · ${esc(m.country_name || m.region)} · ${m.providers.length} провайдеров</p>
      <div class="model-badges"><span class="model-badge country">${esc(m.region)}</span>${m.open_weights ? '<span class="model-badge open">OPEN WEIGHTS</span>' : '<span class="model-badge">PROPRIETARY</span>'}${m.reasoning ? '<span class="model-badge reason">REASONING</span>' : ""}</div></div>
    ${m.description ? `<div class="model-detail-description">${esc(m.description)}</div>` : ""}
    <div class="model-detail-grid">${metrics.map(([name, value]) => `<div class="model-detail-metric"><span>${name}</span><b>${value}</b></div>`).join("")}</div>
    ${b.arena_date ? `<div class="hint">LMArena — исторический снимок от ${esc(b.arena_date)}; голосов: ${esc(b.arena_votes || "—")}. Это не текущий рейтинг на сегодня.</div>` : ""}
    ${ownMetrics}
    <div class="model-detail-section"><h3>Модель и цены</h3><dl class="model-detail-kv">
      <dt>ID</dt><dd>${esc(m.id)}</dd><dt>Контекст</dt><dd>${m.context ? fmt(m.context) + " токенов" : "—"}</dd>
      <dt>Лимит ответа</dt><dd>${m.output_limit ? fmt(m.output_limit) + " токенов" : "—"}</dd>
      <dt>Цена вход / выход</dt><dd>${catalogCost(m)} за 1 млн токенов</dd>
      <dt>Cache read</dt><dd>${catalogMoney(m.cost?.cache_read)} за 1 млн</dd>
      <dt>Релиз</dt><dd>${esc(m.release_date || "—")}</dd><dt>Обновление</dt><dd>${esc(m.last_updated || "—")}</dd>
      <dt>Модальности</dt><dd>${esc((m.modalities?.input || []).join(", ") || "text")} → ${esc((m.modalities?.output || []).join(", ") || "text")}</dd>
      <dt>Инструменты</dt><dd>${m.tool_call == null ? "—" : (m.tool_call ? "да" : "нет")}</dd>
      <dt>Structured output</dt><dd>${m.structured_output == null ? "—" : (m.structured_output ? "да" : "нет")}</dd>
    </dl></div>
    <div class="model-detail-section"><h3>Провайдеры</h3>${m.providers.map(p => `<div class="model-provider-row"><span>${esc(p.name)}</span><span>${p.doc ? `<a href="${esc(p.doc)}" target="_blank" rel="noopener">документация ↗</a>` : esc(p.api || "")}</span></div>`).join("")}</div>
    <div class="model-detail-actions"><button class="btn" id="modelUse">Использовать в прогоне</button><button class="btn ghost" id="modelCopy">Скопировать ID</button><a class="btn ghost" href="${esc(m.source_url)}" target="_blank" rel="noopener">Models.dev ↗</a>${b.aa_slug ? `<a class="btn ghost" href="https://artificialanalysis.ai/models/${esc(b.aa_slug)}" target="_blank" rel="noopener">Artificial Analysis ↗</a>` : ""}</div>`;
  $("#modelUse").onclick = () => {
    if (m.country === "ru") setProv("custom"); else setProv("openrouter");
    $("#model").value = m.id;
    store.set("model." + prov, m.id);
    closeModelDetail(); activateTab("run");
  };
  $("#modelCopy").onclick = async () => {
    try { await navigator.clipboard.writeText(m.id); $("#modelCopy").textContent = "Скопировано ✓"; }
    catch { $("#modelCopy").textContent = m.id; }
  };
  $("#modelBackdrop").classList.remove("hide");
  document.body.style.overflow = "hidden";
}

function closeModelDetail() {
  $("#modelBackdrop").classList.add("hide");
  document.body.style.overflow = "";
}

["modelSearch", "modelRegion", "modelLab", "modelOpen", "modelSort"].forEach(id => $("#" + id).addEventListener("input", () => { catalogState.page = 1; renderCatalog(); }));
$$("[data-model-view]").forEach(btn => btn.onclick = () => {
  catalogState.view = btn.dataset.modelView;
  $$("[data-model-view]").forEach(b => b.classList.toggle("act", b === btn));
  renderCatalog();
});
$$(".models-table th").forEach(th => th.onclick = () => { $("#modelSort").value = th.dataset.sort; renderCatalog(); });
$("#modelsPrev").onclick = () => { catalogState.page--; renderCatalog(); };
$("#modelsNext").onclick = () => { catalogState.page++; renderCatalog(); };
$("#modelsRefresh").onclick = () => refreshCatalog(true);
$("#modelClose").onclick = closeModelDetail;
$("#modelBackdrop").onclick = e => { if (e.target === $("#modelBackdrop")) closeModelDetail(); };
document.addEventListener("keydown", e => { if (e.key === "Escape") closeModelDetail(); });
const savedAA = store.get("aa_key", "");
$("#aaKey").value = savedAA; $("#rememberAA").checked = !!savedAA;
$("#aaKey").addEventListener("input", () => { if ($("#rememberAA").checked) store.set("aa_key", $("#aaKey").value.trim()); });
$("#rememberAA").addEventListener("change", e => store.set("aa_key", e.target.checked ? $("#aaKey").value.trim() : ""));
