const primaryNav = document.querySelector("#primary-nav");
const dashboardNavButton = document.querySelector("#nav-dashboard");
const documentsNavButton = document.querySelector("#nav-documents");
const dashboardControlsSection = document.querySelector("#dashboard-controls-section");
const documentControlsSection = document.querySelector("#document-controls-section");
const workbenchTabs = document.querySelector("#workbench-tabs");
const workbenchTabDocuments = document.querySelector("#workbench-tab-documents");
const workbenchTabArticles = document.querySelector("#workbench-tab-articles");
const manualGmailImportButton = document.querySelector("#manual-gmail-import-button");
const manualGmailImportStatus = document.querySelector("#manual-gmail-import-status");
const summaryBar = document.querySelector("#summary-bar");
const filterForm = document.querySelector("#filter-form");
const sourceFilter = document.querySelector("#source-filter");
const tagFilter = document.querySelector("#tag-filter");
const dateFromFilter = document.querySelector("#date-from-filter");
const dateToFilter = document.querySelector("#date-to-filter");
const resetFiltersButton = document.querySelector("#reset-filters");
const focusTagSection = document.querySelector("#focus-tag-section");
const focusTagCards = document.querySelector("#focus-tag-cards");
const focusTagMeta = document.querySelector("#focus-tag-meta");
const allArticlesSection = document.querySelector("#all-articles-section");
const allArticleCards = document.querySelector("#all-article-cards");
const allArticlesMeta = document.querySelector("#all-articles-meta");
const dashboardStatus = document.querySelector("#dashboard-status");
const articleDetailView = document.querySelector("#article-detail-view");
const detailTitle = document.querySelector("#detail-title");
const detailSummary = document.querySelector("#detail-summary");
const detailMeta = document.querySelector("#detail-meta");
const detailTags = document.querySelector("#detail-tags");
const detailProcessing = document.querySelector("#detail-processing");
const detailOpenDocumentButton = document.querySelector("#detail-open-document-button");
const detailImageGallery = document.querySelector("#detail-image-gallery");
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
const documentProcessingSection = document.querySelector("#document-processing-section");
const documentStatusFilter = document.querySelector("#document-status-filter");
const documentRefreshButton = document.querySelector("#document-refresh-button");
const articleProcessingFilterForm = document.querySelector("#article-processing-filter-form");
const articleProcessingStatusFilter = document.querySelector("#article-processing-status-filter");
const articleProcessingSourceFilter = document.querySelector("#article-processing-source-filter");
const articleProcessingDateFromFilter = document.querySelector("#article-processing-date-from-filter");
const articleProcessingDateToFilter = document.querySelector("#article-processing-date-to-filter");
const articleProcessingResetFiltersButton = document.querySelector("#article-processing-reset-filters");
const documentProcessingMeta = document.querySelector("#document-processing-meta");
const documentProcessingCards = document.querySelector("#document-processing-cards");
const articleProcessingSection = document.querySelector("#article-processing-section");
const articleProcessingMeta = document.querySelector("#article-processing-meta");
const articleProcessingCards = document.querySelector("#article-processing-cards");
const articleProcessingDetailView = document.querySelector("#article-processing-detail-view");
const articleProcessingDetailTitle = document.querySelector("#article-processing-detail-title");
const articleProcessingDetailMeta = document.querySelector("#article-processing-detail-meta");
const articleProcessingDetailBadges = document.querySelector("#article-processing-detail-badges");
const articleProcessingDetailErrorSummary = document.querySelector("#article-processing-detail-error-summary");
const articleProcessingDetailFields = document.querySelector("#article-processing-detail-fields");
const articleProcessingIdentityFields = document.querySelector("#article-processing-identity-fields");
const articleProcessingRetryButton = document.querySelector("#article-processing-retry-button");
const articleProcessingOpenDocumentButton = document.querySelector("#article-processing-open-document-button");
const articleProcessingOpenArticleButton = document.querySelector("#article-processing-open-article-button");
const articleProcessingBackButton = document.querySelector("#article-processing-back-button");
const documentDetailView = document.querySelector("#document-detail-view");
const documentDetailTitle = document.querySelector("#document-detail-title");
const documentDetailMeta = document.querySelector("#document-detail-meta");
const documentDetailBadges = document.querySelector("#document-detail-badges");
const documentDetailError = document.querySelector("#document-detail-error");
const documentIdentityFields = document.querySelector("#document-identity-fields");
const documentErrorSummary = document.querySelector("#document-error-summary");
const documentDetailFields = document.querySelector("#document-detail-fields");
const documentVisibleArticlesMeta = document.querySelector("#document-visible-articles-meta");
const documentVisibleArticles = document.querySelector("#document-visible-articles");
const documentRetryButton = document.querySelector("#document-retry-button");
const documentBackButton = document.querySelector("#document-back-button");
const summaryCardTemplate = document.querySelector("#summary-card-template");
const articleCardTemplate = document.querySelector("#article-card-template");
const documentCardTemplate = document.querySelector("#document-card-template");

let currentDetail = null;
let currentDocumentRun = null;
let currentArticleProcessingRun = null;

async function fetchJson(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: {
      Accept: "application/json",
      ...(options.headers || {}),
    },
  });
  if (!response.ok) {
    throw new Error(`Request failed: ${response.status} ${response.statusText}`);
  }
  return response.json();
}

function setStatus(message) {
  dashboardStatus.textContent = message;
}

function setActiveNav(routeName) {
  [dashboardNavButton, documentsNavButton].forEach((button) => {
    button.classList.remove("active");
  });
  if (routeName === "documents") {
    documentsNavButton.classList.add("active");
    return;
  }
  dashboardNavButton.classList.add("active");
}

function showDashboardSections() {
  dashboardControlsSection.classList.remove("hidden");
  focusTagSection.classList.remove("hidden");
  allArticlesSection.classList.remove("hidden");
  documentControlsSection.classList.add("hidden");
  documentProcessingSection.classList.add("hidden");
  articleProcessingSection.classList.add("hidden");
  articleProcessingDetailView.classList.add("hidden");
  articleProcessingFilterForm.classList.add("hidden");
  documentDetailView.classList.add("hidden");
  setActiveNav("dashboard");
}

function setActiveWorkbenchTab(tabName) {
  [workbenchTabDocuments, workbenchTabArticles].forEach((button) => {
    button.classList.remove("active");
  });
  if (tabName === "articles") {
    workbenchTabArticles.classList.add("active");
    return;
  }
  workbenchTabDocuments.classList.add("active");
}

function showDocumentProcessingPage() {
  dashboardControlsSection.classList.add("hidden");
  focusTagSection.classList.add("hidden");
  allArticlesSection.classList.add("hidden");
  articleDetailView.classList.add("hidden");
  documentControlsSection.classList.remove("hidden");
  documentProcessingSection.classList.remove("hidden");
  articleProcessingSection.classList.add("hidden");
  articleProcessingDetailView.classList.add("hidden");
  articleProcessingFilterForm.classList.add("hidden");
  documentRefreshButton.classList.remove("hidden");
  setActiveWorkbenchTab("documents");
  setActiveNav("documents");
}

function showArticleProcessingPage() {
  dashboardControlsSection.classList.add("hidden");
  focusTagSection.classList.add("hidden");
  allArticlesSection.classList.add("hidden");
  articleDetailView.classList.add("hidden");
  documentDetailView.classList.add("hidden");
  documentControlsSection.classList.remove("hidden");
  documentProcessingSection.classList.add("hidden");
  articleProcessingSection.classList.remove("hidden");
  articleProcessingDetailView.classList.add("hidden");
  articleProcessingFilterForm.classList.remove("hidden");
  documentRefreshButton.classList.add("hidden");
  setActiveWorkbenchTab("articles");
  setActiveNav("documents");
}

function renderSummary(overview) {
  summaryBar.replaceChildren();
  const items = [
    ["今日导入文档", overview.imported_document_count],
    ["今日文章数", overview.article_count],
    ["待翻译文章", overview.pending_article_count],
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
  const currentValue = selectElement.value;
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

  if (options.includes(currentValue) || currentValue === "") {
    selectElement.value = currentValue;
  }
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

function renderDocumentList(runs) {
  documentProcessingCards.replaceChildren();
  if (!runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前筛选条件下没有文档处理记录。";
    documentProcessingCards.appendChild(empty);
    return;
  }

  runs.forEach((run) => {
    const node = documentCardTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".document-card-key").textContent = run.document_key;
    node.querySelector(".document-card-status").textContent = run.status;
    node.querySelector(".document-card-step").textContent = run.current_step;
    node.querySelector(".document-card-updated-at").textContent =
      run.updated_at || "未知更新时间";
    node.querySelector(".document-card-summary").textContent =
      run.last_error_message || "当前没有错误消息，文档可继续处理或等待下一次调度。";

    const badgeRow = node.querySelector(".badge-row");
    [
      `status:${run.status}`,
      `step:${run.current_step}`,
      `failures:${run.automatic_failure_count}`,
    ].forEach((badgeText) => {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = badgeText;
      badgeRow.appendChild(badge);
    });

    node.addEventListener("click", () => {
      window.location.hash = `document/${encodeURIComponent(run.document_key)}`;
    });

    documentProcessingCards.appendChild(node);
  });
}

function renderDocumentVisibleArticles(articles) {
  documentVisibleArticles.replaceChildren();
  if (!articles.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前文档还没有可见文章输出。";
    documentVisibleArticles.appendChild(empty);
    documentVisibleArticlesMeta.textContent = "当前可见文章 0 篇";
    return;
  }

  articles.forEach((article) => {
    const node = articleCardTemplate.content.firstElementChild.cloneNode(true);
    node.dataset.articleId = article.article_id;
    node.querySelector(".card-source").textContent = article.reading_status;
    node.querySelector(".card-date").textContent = article.publication_date;
    node.querySelector(".card-title").textContent = article.title_zh || article.title_en;
    node.querySelector(".card-summary").textContent =
      article.summary_zh || "当前没有中文摘要，可点击进入文章详情查看正文。";

    const badgeRow = node.querySelector(".badge-row");
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = article.reading_status;
    badgeRow.appendChild(badge);

    node.addEventListener("click", () => {
      window.location.hash = `article/${article.article_id}`;
    });

    documentVisibleArticles.appendChild(node);
  });

  documentVisibleArticlesMeta.textContent = `当前可见文章 ${articles.length} 篇`;
}

function renderArticleProcessingList(runs) {
  articleProcessingCards.replaceChildren();
  if (!runs.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前没有文章处理记录。";
    articleProcessingCards.appendChild(empty);
    return;
  }

  runs.forEach((run) => {
    const node = documentCardTemplate.content.firstElementChild.cloneNode(true);
    node.querySelector(".document-card-key").textContent = run.title_en || run.article_key;
    node.querySelector(".document-card-status").textContent = run.status;
    node.querySelector(".document-card-step").textContent = run.current_step;
    node.querySelector(".document-card-updated-at").textContent =
      run.publication_date || "未知日期";
    node.querySelector(".document-card-summary").textContent =
      run.latest_error_summary || "当前没有错误消息。";

    const badgeRow = node.querySelector(".badge-row");
    [
      run.source_name || "未知来源",
      `pages:${(run.source_page_numbers || []).join(",") || "n/a"}`,
      `failures:${run.automatic_failure_count ?? 0}`,
    ].forEach((badgeText) => {
      const badge = document.createElement("span");
      badge.className = "badge";
      badge.textContent = badgeText;
      badgeRow.appendChild(badge);
    });

    node.addEventListener("click", () => {
      window.location.hash = `article-processing/${encodeURIComponent(run.article_key)}`;
    });

    articleProcessingCards.appendChild(node);
  });
}

function showArticleProcessingDetail(run) {
  currentArticleProcessingRun = run;
  showArticleProcessingPage();
  articleProcessingDetailView.classList.remove("hidden");
  articleProcessingDetailTitle.textContent = run.title_en || run.article_key;
  articleProcessingDetailMeta.textContent =
    `状态 ${run.status} · 当前步骤 ${run.current_step}`;
  articleProcessingDetailErrorSummary.textContent =
    run.latest_error_summary || "当前没有错误。";
  articleProcessingDetailBadges.replaceChildren();
  [
    `status:${run.status}`,
    `step:${run.current_step}`,
    `failures:${run.automatic_failure_count ?? 0}`,
  ].forEach((badgeText) => {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = badgeText;
    articleProcessingDetailBadges.appendChild(badge);
  });

  articleProcessingIdentityFields.replaceChildren();
  [
    ["来源", run.source_name || "无"],
    ["原始文件名", run.original_filename || "无"],
    ["发布日期", run.publication_date || "无"],
    ["页码", (run.source_page_numbers || []).join(", ") || "无"],
    ["文档键", run.document_key || "无"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "key-value-row";
    const key = document.createElement("span");
    key.className = "key-value-label";
    key.textContent = label;
    const text = document.createElement("span");
    text.className = "key-value-value";
    text.textContent = value;
    row.appendChild(key);
    row.appendChild(text);
    articleProcessingIdentityFields.appendChild(row);
  });

  articleProcessingDetailFields.replaceChildren();
  [
    ["上次开始时间", run.last_attempt_started_at || "无"],
    ["上次结束时间", run.last_attempt_finished_at || "无"],
    ["锁定执行器", run.locked_by || "无"],
    ["锁过期时间", run.lock_expires_at || "无"],
    ["最近成功输入哈希", run.last_success_input_hash || "无"],
    ["最近更新时间", run.updated_at || "无"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "key-value-row";
    const key = document.createElement("span");
    key.className = "key-value-label";
    key.textContent = label;
    const text = document.createElement("span");
    text.className = "key-value-value";
    text.textContent = value;
    row.appendChild(key);
    row.appendChild(text);
    articleProcessingDetailFields.appendChild(row);
  });

  articleProcessingRetryButton.disabled = run.status === "running";
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

function buildDocumentProcessingQueryString() {
  const params = new URLSearchParams();
  if (documentStatusFilter.value) {
    params.set("status", documentStatusFilter.value);
  }
  return params.toString();
}

function buildArticleProcessingQueryString() {
  const params = new URLSearchParams();
  if (articleProcessingStatusFilter.value) {
    params.set("status", articleProcessingStatusFilter.value);
  }
  if (articleProcessingSourceFilter.value) {
    params.set("source", articleProcessingSourceFilter.value);
  }
  if (articleProcessingDateFromFilter.value) {
    params.set("publication_date_from", articleProcessingDateFromFilter.value);
  }
  if (articleProcessingDateToFilter.value) {
    params.set("publication_date_to", articleProcessingDateToFilter.value);
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
  renderSelectOptions(articleProcessingSourceFilter, payload.filters.sources, "全部来源");
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

function renderDetailImages(images) {
  detailImageGallery.replaceChildren();
  if (!images?.length) {
    detailImageGallery.classList.add("hidden");
    return;
  }

  images.forEach((imagePath, index) => {
    const image = document.createElement("img");
    image.className = "detail-image";
    image.src = `/api/local-image?path=${encodeURIComponent(imagePath)}`;
    image.alt = `${currentDetail?.title_zh || currentDetail?.title_en || "article"} image ${index + 1}`;
    image.loading = "lazy";
    detailImageGallery.appendChild(image);
  });
  detailImageGallery.classList.remove("hidden");
}

function showArticleDetail(detail) {
  currentDetail = detail;
  showDashboardSections();
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
  renderDetailImages(detail.images || []);
  detailZhBody.textContent = detail.body_text_zh || "当前没有中文正文。";
  detailEnBody.textContent = detail.body_text_en;
  renderDetailMode("zh");
  articleDetailView.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadArticleDetail(articleId) {
  setStatus("正在加载文章详情...");
  const payload = await fetchJson(`/api/articles/${articleId}`);
  showArticleDetail(payload.article);
  setStatus("文章详情已加载。");
}

function openSourceDocumentFromArticleDetail() {
  if (!currentDetail?.document_key) {
    setStatus("当前文章没有可用的源文档标识。");
    return;
  }
  window.location.hash = `document/${encodeURIComponent(currentDetail.document_key)}`;
}

function showDocumentDetail(run) {
  currentDocumentRun = run;
  showDocumentProcessingPage();
  documentDetailView.classList.remove("hidden");
  documentDetailTitle.textContent = run.document_key;
  documentDetailMeta.textContent =
    `状态 ${run.status} · 当前步骤 ${run.current_step}`;

  documentDetailBadges.replaceChildren();
  [
    `status:${run.status}`,
    `step:${run.current_step}`,
    `failures:${run.automatic_failure_count}`,
  ].forEach((badgeText) => {
    const badge = document.createElement("span");
    badge.className = "badge";
    badge.textContent = badgeText;
    documentDetailBadges.appendChild(badge);
  });

  documentDetailError.textContent =
    run.last_error_message || "当前没有错误消息。";
  documentErrorSummary.textContent =
    run.latest_error_summary || "当前没有错误。";

  documentIdentityFields.replaceChildren();
  [
    ["来源", run.source_name || "无"],
    ["原始文件名", run.original_filename || "无"],
    ["发送方", run.sender || "无"],
    ["导入状态", run.import_status || "无"],
    ["原始路径", run.raw_path || "无"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "key-value-row";
    const key = document.createElement("span");
    key.className = "key-value-label";
    key.textContent = label;
    const text = document.createElement("span");
    text.className = "key-value-value";
    text.textContent = value;
    row.appendChild(key);
    row.appendChild(text);
    documentIdentityFields.appendChild(row);
  });

  documentDetailFields.replaceChildren();
  [
    ["上次失败步骤", run.last_failure_step || "无"],
    ["上次开始时间", run.last_attempt_started_at || "无"],
    ["上次结束时间", run.last_attempt_finished_at || "无"],
    ["锁定执行器", run.locked_by || "无"],
    ["锁过期时间", run.lock_expires_at || "无"],
    ["最近更新时间", run.updated_at || "无"],
  ].forEach(([label, value]) => {
    const row = document.createElement("div");
    row.className = "key-value-row";
    const key = document.createElement("span");
    key.className = "key-value-label";
    key.textContent = label;
    const text = document.createElement("span");
    text.className = "key-value-value";
    text.textContent = value;
    row.appendChild(key);
    row.appendChild(text);
    documentDetailFields.appendChild(row);
  });

  renderDocumentVisibleArticles(run.visible_articles || []);
  documentRetryButton.disabled = run.status === "running";
  documentDetailView.scrollIntoView({ behavior: "smooth", block: "start" });
}

async function loadDocumentProcessing() {
  showDocumentProcessingPage();
  setStatus("正在加载文档处理列表...");
  const queryString = buildDocumentProcessingQueryString();
  const path = queryString
    ? `/api/document-processing?${queryString}`
    : "/api/document-processing";
  const payload = await fetchJson(path);
  renderDocumentList(payload.runs);
  documentProcessingMeta.textContent = `当前列表共 ${payload.runs.length} 条记录`;
  setStatus("文档处理列表已加载。");
}

async function loadArticleProcessing() {
  showArticleProcessingPage();
  setStatus("正在加载文章处理列表...");
  const queryString = buildArticleProcessingQueryString();
  const path = queryString ? `/api/article-processing?${queryString}` : "/api/article-processing";
  const payload = await fetchJson(path);
  renderArticleProcessingList(payload.runs);
  articleProcessingMeta.textContent = `当前列表共 ${payload.runs.length} 条记录`;
  setStatus("文章处理列表已加载。");
}

async function loadArticleProcessingDetail(articleKey) {
  showArticleProcessingPage();
  setStatus("正在加载文章处理详情...");
  const payload = await fetchJson(`/api/article-processing/${encodeURIComponent(articleKey)}`);
  showArticleProcessingDetail(payload.run);
  setStatus("文章处理详情已加载。");
}

async function loadDocumentDetail(documentKey) {
  showDocumentProcessingPage();
  setStatus("正在加载文档处理详情...");
  const payload = await fetchJson(`/api/document-processing/${encodeURIComponent(documentKey)}`);
  showDocumentDetail(payload.run);
  setStatus("文档处理详情已加载。");
}

async function requestManualRetry(documentKey) {
  setStatus("正在请求手动重试...");
  const payload = await fetchJson(
    `/api/document-processing/${encodeURIComponent(documentKey)}/retry`,
    { method: "POST" },
  );
  showDocumentDetail(payload.run);
  await loadDocumentProcessing();
  showDocumentDetail(payload.run);
  setStatus("已请求手动重试。");
}

async function requestManualArticleRetry(articleKey) {
  setStatus("正在请求文章重试...");
  const payload = await fetchJson(
    `/api/article-processing/${encodeURIComponent(articleKey)}/retry`,
    { method: "POST" },
  );
  showArticleProcessingDetail(payload.run);
  await loadArticleProcessing();
  showArticleProcessingDetail(payload.run);
  setStatus("已请求文章重试。");
}

function formatManualGmailImportSummary(importRun) {
  const createdCount = importRun?.created_document_count ?? 0;
  const skippedCount = importRun?.skipped_document_count ?? 0;
  const attachmentCount = importRun?.imported_attachment_count ?? 0;
  if (createdCount === 0) {
    return `已检查邮件，没有新增文档；跳过 ${skippedCount} 项。`;
  }
  return `已导入 ${createdCount} 个新文档、${attachmentCount} 个附件；跳过 ${skippedCount} 项。`;
}

async function requestManualGmailImport() {
  manualGmailImportButton.disabled = true;
  manualGmailImportButton.textContent = "拉取中...";
  manualGmailImportStatus.textContent = "正在检查最新邮件附件...";
  setStatus("正在手动拉取邮件...");
  try {
    const payload = await fetchJson("/api/gmail/import", { method: "POST" });
    manualGmailImportStatus.textContent = formatManualGmailImportSummary(payload.import_run);
    await loadDocumentProcessing();
    setStatus("邮件拉取完成，处理队列会自动接手。");
  } catch (error) {
    console.error(error);
    manualGmailImportStatus.textContent = "邮件拉取失败，请稍后重试。";
    setStatus("邮件拉取失败，请检查后端服务和 Gmail 配置。");
  } finally {
    manualGmailImportButton.disabled = false;
    manualGmailImportButton.textContent = "立即拉取邮件";
  }
}

async function syncRouteFromHash() {
  const hash = window.location.hash.replace(/^#/, "").trim();
  if (!hash || hash === "dashboard") {
    showDashboardSections();
    articleDetailView.classList.add("hidden");
    return;
  }

  if (hash === "documents") {
    documentDetailView.classList.add("hidden");
    await loadDocumentProcessing();
    return;
  }

  if (hash === "articles-processing") {
    documentDetailView.classList.add("hidden");
    await loadArticleProcessing();
    return;
  }

  if (hash.startsWith("article/")) {
    const articleId = hash.replace("article/", "").trim();
    if (!articleId) {
      showDashboardSections();
      articleDetailView.classList.add("hidden");
      return;
    }
    await loadArticleDetail(articleId);
    return;
  }

  if (hash.startsWith("article-processing/")) {
    const articleKey = decodeURIComponent(hash.replace("article-processing/", "").trim());
    if (!articleKey) {
      await loadArticleProcessing();
      return;
    }
    await loadArticleProcessingDetail(articleKey);
    return;
  }

  if (hash.startsWith("document/")) {
    const documentKey = decodeURIComponent(hash.replace("document/", "").trim());
    if (!documentKey) {
      await loadDocumentProcessing();
      return;
    }
    await loadDocumentDetail(documentKey);
    return;
  }

  showDashboardSections();
  articleDetailView.classList.add("hidden");
  setStatus("未识别的页面路由，已返回首页。");
}

async function loadDashboard() {
  setStatus("正在刷新首页数据...");
  try {
    await Promise.all([loadOverview(), loadFilters(), loadFocusTagArticles(), loadAllArticles()]);
    setStatus("数据已同步。");
  } catch (error) {
    console.error(error);
    setStatus("加载失败，请确认 frontend 代理和 API 服务已启动。");
  }
  try {
    await syncRouteFromHash();
  } catch (error) {
    console.error(error);
    setStatus("当前页面加载失败，请稍后重试。");
  }
}

primaryNav.addEventListener("click", (event) => {
  const button = event.target.closest("[data-route]");
  if (!button) {
    return;
  }
  window.location.hash = button.dataset.route;
});

workbenchTabs.addEventListener("click", (event) => {
  const button = event.target.closest("[data-route]");
  if (!button) {
    return;
  }
  window.location.hash = button.dataset.route;
});

filterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  setStatus("正在根据筛选条件刷新文章...");
  try {
    await loadAllArticles();
    setStatus("文章列表已更新。");
  } catch (error) {
    console.error(error);
    setStatus("筛选失败，请稍后重试。");
  }
});

resetFiltersButton.addEventListener("click", async () => {
  filterForm.reset();
  setStatus("正在重置筛选条件...");
  try {
    await loadAllArticles();
    setStatus("已恢复默认列表。");
  } catch (error) {
    console.error(error);
    setStatus("重置失败，请稍后重试。");
  }
});

documentRefreshButton.addEventListener("click", async () => {
  try {
    await loadDocumentProcessing();
  } catch (error) {
    console.error(error);
    setStatus("文档处理列表刷新失败。");
  }
});

manualGmailImportButton.addEventListener("click", () => {
  requestManualGmailImport();
});

documentStatusFilter.addEventListener("change", async () => {
  try {
    await loadDocumentProcessing();
  } catch (error) {
    console.error(error);
    setStatus("文档处理筛选失败。");
  }
});

articleProcessingFilterForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadArticleProcessing();
  } catch (error) {
    console.error(error);
    setStatus("文章处理筛选失败。");
  }
});

articleProcessingResetFiltersButton.addEventListener("click", async () => {
  articleProcessingFilterForm.reset();
  try {
    await loadArticleProcessing();
  } catch (error) {
    console.error(error);
    setStatus("文章处理筛选重置失败。");
  }
});

detailBackButton.addEventListener("click", () => {
  window.location.hash = "dashboard";
  articleDetailView.classList.add("hidden");
});

detailOpenDocumentButton.addEventListener("click", () => {
  openSourceDocumentFromArticleDetail();
});

articleProcessingBackButton.addEventListener("click", () => {
  window.location.hash = "articles-processing";
  articleProcessingDetailView.classList.add("hidden");
});

articleProcessingOpenDocumentButton.addEventListener("click", () => {
  if (!currentArticleProcessingRun?.document_key) {
    setStatus("当前文章处理记录没有可用的所属文档。");
    return;
  }
  window.location.hash = `document/${encodeURIComponent(currentArticleProcessingRun.document_key)}`;
});

articleProcessingOpenArticleButton.addEventListener("click", () => {
  if (!currentArticleProcessingRun?.article_id) {
    setStatus("当前文章处理记录没有可用的文章标识。");
    return;
  }
  window.location.hash = `article/${encodeURIComponent(currentArticleProcessingRun.article_id)}`;
});

articleProcessingRetryButton.addEventListener("click", async () => {
  if (!currentArticleProcessingRun?.article_key) {
    return;
  }
  try {
    await requestManualArticleRetry(currentArticleProcessingRun.article_key);
  } catch (error) {
    console.error(error);
    setStatus("文章手动重试请求失败。");
  }
});

documentBackButton.addEventListener("click", () => {
  window.location.hash = "documents";
  documentDetailView.classList.add("hidden");
});

documentRetryButton.addEventListener("click", async () => {
  if (!currentDocumentRun) {
    return;
  }
  try {
    await requestManualRetry(currentDocumentRun.document_key);
  } catch (error) {
    console.error(error);
    setStatus("手动重试请求失败。");
  }
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
  syncRouteFromHash().catch((error) => {
    console.error(error);
    setStatus("页面切换失败，请稍后重试。");
  });
});

loadDashboard();
