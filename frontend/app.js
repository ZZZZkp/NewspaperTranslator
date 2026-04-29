const summaryBar = document.querySelector("#summary-bar");
const filterForm = document.querySelector("#filter-form");
const sourceFilter = document.querySelector("#source-filter");
const tagFilter = document.querySelector("#tag-filter");
const dateFromFilter = document.querySelector("#date-from-filter");
const dateToFilter = document.querySelector("#date-to-filter");
const resetFiltersButton = document.querySelector("#reset-filters");
const focusTagCards = document.querySelector("#focus-tag-cards");
const focusTagMeta = document.querySelector("#focus-tag-meta");
const allArticleCards = document.querySelector("#all-article-cards");
const allArticlesMeta = document.querySelector("#all-articles-meta");
const dashboardStatus = document.querySelector("#dashboard-status");
const articleDetailView = document.querySelector("#article-detail-view");
const detailTitle = document.querySelector("#detail-title");
const detailSummary = document.querySelector("#detail-summary");
const detailMeta = document.querySelector("#detail-meta");
const detailTags = document.querySelector("#detail-tags");
const detailProcessing = document.querySelector("#detail-processing");
const detailSingleTitle = document.querySelector("#detail-single-title");
const detailSingleBody = document.querySelector("#detail-single-body");
const detailZhBody = document.querySelector("#detail-zh-body");
const detailEnBody = document.querySelector("#detail-en-body");
const detailBackButton = document.querySelector("#detail-back-button");
const modeZhButton = document.querySelector("#mode-zh");
const modeEnButton = document.querySelector("#mode-en");
const modeCompareButton = document.querySelector("#mode-compare");
const detailSinglePane = document.querySelector("#detail-single-pane");
const detailComparePane = document.querySelector("#detail-compare-pane");
const summaryCardTemplate = document.querySelector("#summary-card-template");
const articleCardTemplate = document.querySelector("#article-card-template");

let currentDetail = null;

async function fetchJson(path) {
  const response = await fetch(path, {
    headers: {
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function renderSummary(overview) {
  summaryBar.replaceChildren();
  const items = [
    ["今日导入文档", overview.imported_document_count],
    ["今日文章数", overview.article_count],
    ["处理中", overview.processing_document_count],
    ["待处理异常", overview.pending_exception_count],
  ];
  items.forEach(([label, value]) => {
    const node = summaryCardTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".summary-label").textContent = label;
    node.querySelector(".summary-value").textContent = String(value);
    summaryBar.appendChild(node);
  });
}

function renderSelectOptions(selectElement, options, emptyLabel) {
  selectElement.replaceChildren();
  const emptyOption = document.createElement("option");
  emptyOption.value = "";
  emptyOption.textContent = emptyLabel;
  selectElement.appendChild(emptyOption);

  options.forEach((optionValue) => {
    const option = document.createElement("option");
    option.value = optionValue;
    option.textContent = optionValue;
    selectElement.appendChild(option);
  });
}

function renderCards(container, cards, emptyText) {
  container.replaceChildren();
  if (!cards.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = emptyText;
    container.appendChild(empty);
    return;
  }

  cards.forEach((card) => {
    const node = articleCardTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.articleId = card.article_id;
    node.querySelector(".card-source").textContent = card.source_name;
    node.querySelector(".card-date").textContent = card.publication_date;
    node.querySelector(".card-title").textContent = card.title_zh || card.title_en;
    node.querySelector(".card-summary").textContent =
      card.summary_zh || "当前没有中文摘要，已降级为英文阅读模式。";

    const badgeRow = node.querySelector(".badge-row");
    (card.processing_badges || []).forEach((badgeText) => {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = badgeText;
      badgeRow.appendChild(badge);
    });
    if (card.reading_status === "english_fallback") {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = "english_fallback";
      badgeRow.appendChild(badge);
    }

    const tagRow = node.querySelector(".tag-row");
    (card.tags || []).forEach((tagText) => {
      const tag = document.createElement("span");
      tag.className = "tag";
      tag.textContent = tagText;
      tagRow.appendChild(tag);
    });

    node.addEventListener("click", () => {
      window.location.hash = `article/${card.article_id}`;
    });

    container.appendChild(node);
  });
}

function buildArticleQueryString() {
  const params = new URLSearchParams();
  if (sourceFilter.value) {
    params.set("source", sourceFilter.value);
  }
  if (tagFilter.value) {
    params.set("tag", tagFilter.value);
  }
  if (dateFromFilter.value) {
    params.set("publication_date_from", dateFromFilter.value);
  }
  if (dateToFilter.value) {
    params.set("publication_date_to", dateToFilter.value);
  }
  return params.toString();
}

async function loadOverview() {
  const payload = await fetchJson("/api/overview");
  renderSummary(payload.overview);
}

async function loadFilters() {
  const payload = await fetchJson("/api/filters");
  renderSelectOptions(sourceFilter, payload.filters.sources, "全部来源");
  renderSelectOptions(tagFilter, payload.filters.tags, "全部标签");
}

async function loadFocusTagArticles() {
  const payload = await fetchJson("/api/focus-tags/articles");
  renderCards(
    focusTagCards,
    payload.articles,
    "当前没有命中关注标签的文章。",
  );
  focusTagMeta.textContent = `共 ${payload.articles.length} 篇文章命中关注标签`;
}

async function loadAllArticles() {
  const queryString = buildArticleQueryString();
  const path = queryString ? `/api/articles?${queryString}` : "/api/articles";
  const payload = await fetchJson(path);
  renderCards(
    allArticleCards,
    payload.articles,
    "当前筛选条件下没有文章。",
  );
  allArticlesMeta.textContent = `当前列表共 ${payload.articles.length} 篇文章`;
}

function renderDetailMode(mode) {
  [modeZhButton, modeEnButton, modeCompareButton].forEach((button) => {
    button.classList.remove("active");
  });

  if (mode === "compare") {
    modeCompareButton.classList.add("active");
    detailSinglePane.classList.add("hidden");
    detailComparePane.classList.remove("hidden");
    return;
  }

  detailSinglePane.classList.remove("hidden");
  detailComparePane.classList.add("hidden");

  if (mode === "en") {
    modeEnButton.classList.add("active");
    detailSingleTitle.textContent = currentDetail.title_en;
    detailSingleBody.textContent = currentDetail.body_text_en;
    return;
  }

  modeZhButton.classList.add("active");
  detailSingleTitle.textContent = currentDetail.title_zh || currentDetail.title_en;
  detailSingleBody.textContent = currentDetail.body_text_zh || currentDetail.body_text_en;
}

function showArticleDetail(detail) {
  currentDetail = detail;
  articleDetailView.classList.remove("hidden");
  detailTitle.textContent = detail.title_zh || detail.title_en;
  detailSummary.textContent = detail.summary_zh || "当前没有中文摘要。";
  detailMeta.textContent = `${detail.source_name} · ${detail.publication_date}`;
  detailTags.replaceChildren();
  (detail.tags || []).forEach((tagText) => {
    const tag = document.createElement("span");
    tag.className = "tag";
    tag.textContent = tagText;
    detailTags.appendChild(tag);
  });
  detailProcessing.replaceChildren();
  Object.entries(detail.processing || {}).forEach(([key, value]) => {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = `${key}: ${value}`;
    detailProcessing.appendChild(badge);
  });
  detailZhBody.textContent = detail.body_text_zh || "当前没有中文正文。";
  detailEnBody.textContent = detail.body_text_en;
  renderDetailMode("zh");
  articleDetailView.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadArticleDetail(articleId) {
  dashboardStatus.textContent = "正在加载文章详情...";
  const payload = await fetchJson(`/api/articles/${articleId}`);
  showArticleDetail(payload.article);
  dashboardStatus.textContent = "文章详情已加载。";
}

async function syncRouteFromHash() {
  const hash = window.location.hash.replace(/^#/, "");
  if (!hash.startsWith("article/")) {
    articleDetailView.classList.add("hidden");
    return;
  }

  const articleId = hash.replace("article/", "").trim();
  if (!articleId) {
    articleDetailView.classList.add("hidden");
    return;
  }

  try {
    await loadArticleDetail(articleId);
  } catch (error) {
    console.error(error);
    dashboardStatus.textContent = "文章详情加载失败。";
  }
}

async function loadDashboard() {
  dashboardStatus.textContent = "正在刷新首页数据...";
  try {
    await Promise.all([loadOverview(), loadFilters(), loadFocusTagArticles(), loadAllArticles()]);
    dashboardStatus.textContent = "数据已同步。";
  } catch (error) {
    console.error(error);
    dashboardStatus.textContent = "加载失败，请确认 frontend 代理和 API 服务已启动。";
  }
  await syncRouteFromHash();
}

filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  dashboardStatus.textContent = "正在根据筛选条件刷新文章...";
  try {
    await loadAllArticles();
    dashboardStatus.textContent = "文章列表已更新。";
  } catch (error) {
    console.error(error);
    dashboardStatus.textContent = "筛选失败，请稍后重试。";
  }
});

resetFiltersButton.addEventListener("click", async () => {
  filterForm.reset();
  dashboardStatus.textContent = "正在重置筛选条件...";
  try {
    await loadAllArticles();
    dashboardStatus.textContent = "已恢复默认列表。";
  } catch (error) {
    console.error(error);
    dashboardStatus.textContent = "重置失败，请稍后重试。";
  }
});

detailBackButton.addEventListener("click", () => {
  window.location.hash = "";
  articleDetailView.classList.add("hidden");
});

modeZhButton.addEventListener("click", () => {
  if (currentDetail) {
    renderDetailMode("zh");
  }
});

modeEnButton.addEventListener("click", () => {
  if (currentDetail) {
    renderDetailMode("en");
  }
});

modeCompareButton.addEventListener("click", () => {
  if (currentDetail) {
    renderDetailMode("compare");
  }
});

window.addEventListener("hashchange", () => {
  syncRouteFromHash();
});

loadDashboard();
