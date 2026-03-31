let data = null;
let matches = [];
let currentMatchIndex = -1;

const searchInput = document.getElementById('searchInput');
const prevBtn = document.getElementById('prevBtn');
const nextBtn = document.getElementById('nextBtn');
const matchBadge = document.getElementById('matchBadge');
const content = document.getElementById('content');

function render() {
  if (!data?.pages?.length) {
    content.innerHTML = '<div class="empty-state"><p>유효한 OCR 데이터가 없습니다.</p></div>';
    return;
  }

  content.innerHTML = data.pages.map((page, i) => {
    const imgSrc = page.image ? `data:image/png;base64,${page.image}` : '';
    const w = page.width || 800;
    const h = page.height || 600;
    
    const textSpans = (page.texts || []).map((t, textIdx) => {
      const b = t.bbox;
      if (!b || b.length < 4) return '';
      const [x1, y1, x2, y2] = b;
      const boxH = y2 - y1;
      const boxW = x2 - x1;
      const fs = Math.max(6, Math.round(boxH * 0.72));
      const text = t.text || '';
      return `<span data-page="${i}" data-text-idx="${textIdx}" 
        style="left:${x1}px;top:${y1}px;width:${boxW}px;height:${boxH}px;font-size:${fs}px;line-height:${boxH}px">${escapeHtml(text)}</span>`;
    }).join('');
    
    const boxes = (page.texts || []).map((t, textIdx) => {
      const b = t.bbox;
      if (!b || b.length < 4) return '';
      const [x1, y1, x2, y2] = b;
      const boxH = y2 - y1;
      return `<div class="word-box" data-page="${i}" data-text-idx="${textIdx}" data-text="${escapeHtml(t.text)}" 
        style="left:${x1}px;top:${y1}px;width:${x2-x1}px;height:${boxH}px"></div>`;
    }).join('');
    
    return `
      <div class="page-card" id="page-${i}" data-page-index="${i}">
        <div class="page-header">페이지 ${page.page}</div>
        <div class="page-body" data-natural-w="${w}" data-natural-h="${h}">
          <img class="page-img" src="${imgSrc}" alt="Page ${page.page}">
          <div class="page-overlay" style="width:${w}px;height:${h}px">
            <div class="text-layer">${textSpans}</div>
            ${boxes}
          </div>
        </div>
      </div>`;
  }).join('');

  searchInput.disabled = false;

  const finishNavHint = () => {
    const hint = window.__pendingNavHint;
    window.__pendingNavHint = null;
    if (hint) applyNavigationHint(hint);
  };
  let pendingImages = 0;
  document.querySelectorAll('.page-body').forEach(body => {
    const img = body.querySelector('.page-img');
    const overlay = body.querySelector('.page-overlay');
    if (!img || !overlay) return;
    pendingImages += 1;
    const scale = () => {
      const r = img.getBoundingClientRect();
      const sc = r.width / img.naturalWidth;
      overlay.style.transform = `scale(${sc})`;
      overlay.style.transformOrigin = 'top left';
      overlay.style.width = img.naturalWidth + 'px';
      overlay.style.height = img.naturalHeight + 'px';
    };
    const done = () => {
      scale();
      if (--pendingImages <= 0) finishNavHint();
    };
    if (img.complete) done();
    else img.addEventListener('load', done, { once: true });
  });
  if (pendingImages === 0) finishNavHint();

  doSearch();
}

function applyNavigationHint(meta) {
  document.querySelectorAll('.external-focus-rect').forEach(el => el.remove());
  
  if (!meta || !data?.pages?.length) return;
  const targetPage = meta.page;
  const bbox = meta.bbox;
  const article = meta.article_title;

  let pageIdx = 0;
  if (targetPage != null) {
    const found = data.pages.findIndex((p) => p.page === targetPage);
    if (found >= 0) pageIdx = found;
  }

  const card = document.getElementById(`page-${pageIdx}`);
  if (card) {
    document.querySelectorAll('.page-card').forEach(c => c.classList.remove('highlight'));
    card.classList.add('highlight');
    card.scrollIntoView({ behavior: 'smooth', block: 'center' });
  }

  if (bbox && bbox.x0 != null && bbox.y0 != null && bbox.x1 != null && bbox.y1 != null) {
    const body = card && card.querySelector('.page-body');
    const overlay = body && body.querySelector('.page-overlay');
    const img = body && body.querySelector('.page-img');
    if (overlay && img && img.naturalWidth) {
      const w = img.naturalWidth;
      const h = img.naturalHeight;
      const el = document.createElement('div');
      el.className = 'external-focus-rect';
      el.style.left = (bbox.x0 * w) + 'px';
      el.style.top = (bbox.y0 * h) + 'px';
      el.style.width = Math.max(8, (bbox.x1 - bbox.x0) * w) + 'px';
      el.style.height = Math.max(8, (bbox.y1 - bbox.y0) * h) + 'px';
      overlay.appendChild(el);
      
      setTimeout(() => {
        el.style.transition = 'opacity 0.3s ease';
        el.style.opacity = '0';
        setTimeout(() => el.remove(), 300);
      }, 2000);
    }
  }

  if (article && String(article).trim()) {
    searchInput.disabled = false;
    searchInput.value = article.trim();
    doSearch();
    if (matches.length > 0) goToMatch(0);
  }
}

function escapeHtml(s) {
  const d = document.createElement('div');
  d.textContent = s;
  return d.innerHTML.replace(/"/g, '&quot;');
}

function normalizeForSearch(s) {
  return String(s)
    .toLowerCase()
    .normalize('NFKC')
    .replace(/[\u200b-\u200d\ufeff\u2060\ufffc]/g, '')
    .replace(/[\s\u00ad\u034f\u115f\u1160\u17db\u180e\u2800\u3164]+/g, '');
}

/**
 * 한 칼럼 안에서만 위→아래, 같은 줄은 왼→오.
 * (전역 y→x 정렬은 이중어에서 같은 줄의 영어가 한글 줄 사이에 끼어 줄바꿈 검색이 깨짐)
 */
function sortColumnReadingOrder(texts, columnItems) {
  if (columnItems.length === 0) return [];
  const items = columnItems.slice();
  const heights = items.map((it) => it.h).sort((a, b) => a - b);
  const medH = heights[Math.floor(heights.length / 2)] || 12;
  const yBand = Math.max(10, medH * 0.45);
  items.sort((a, b) => {
    const la = Math.round(a.ymid / yBand);
    const lb = Math.round(b.ymid / yBand);
    if (la !== lb) return la - lb;
    return a.x1 - b.x1;
  });
  return items.map((it) => it.i);
}

/**
 * splitX 기준으로 좌·우로 나눈 뒤 칼럼마다 읽기 순서. 양쪽에 박스가 충분할 때만 사용.
 */
function trySplitAtX(texts, items, splitX, pageW) {
  const left = items.filter((it) => it.xmid < splitX);
  const right = items.filter((it) => it.xmid >= splitX);
  const minEach = Math.max(2, Math.ceil(items.length * 0.06));
  const wideEnough = pageW >= 280;
  if (!wideEnough || left.length < minEach || right.length < minEach) {
    return null;
  }
  return [...sortColumnReadingOrder(texts, left), ...sortColumnReadingOrder(texts, right)];
}

/**
 * 1) x 중심 간격이 큰 지점으로 좌·우 분리 (요구 간격을 비교적 작게)
 * 2) 실패 시 페이지 세로 중앙선(pageW/2)으로 분리 시도
 * 3) 그래도 안 되면 단일 칼럼
 */
function readingOrderTextIndices(page) {
  const texts = page.texts || [];
  const items = [];
  for (let i = 0; i < texts.length; i++) {
    const b = texts[i].bbox;
    if (!b || b.length < 4) continue;
    const ymid = (b[1] + b[3]) / 2;
    items.push({
      i,
      ymid,
      x1: b[0],
      x2: b[2],
      xmid: (b[0] + b[2]) / 2,
      h: b[3] - b[1],
    });
  }
  if (items.length === 0) return [];

  const pageW = page.width || Math.max(0, ...items.map((it) => it.x2)) || 800;
  const minColGap = Math.max(18, pageW * 0.03);
  const byX = [...items].sort((a, b) => a.xmid - b.xmid);
  let bestGap = 0;
  let splitJ = -1;
  for (let j = 0; j < byX.length - 1; j++) {
    const g = byX[j + 1].xmid - byX[j].xmid;
    if (g > bestGap) {
      bestGap = g;
      splitJ = j;
    }
  }
  if (bestGap >= minColGap && splitJ >= 0) {
    const splitX = (byX[splitJ].xmid + byX[splitJ + 1].xmid) / 2;
    const left = items.filter((it) => it.xmid < splitX);
    const right = items.filter((it) => it.xmid >= splitX);
    return [...sortColumnReadingOrder(texts, left), ...sortColumnReadingOrder(texts, right)];
  }
  const mid = trySplitAtX(texts, items, pageW * 0.5, pageW);
  if (mid) return mid;
  return sortColumnReadingOrder(texts, items);
}

function buildPageConcatNorm(page, order) {
  const texts = page.texts || [];
  let full = '';
  const segs = [];
  for (let i = 0; i < order.length; i++) {
    const ti = order[i];
    const n = normalizeForSearch(texts[ti].text || '');
    if (!n) continue;
    const start = full.length;
    full += n;
    segs.push({ ti, start: start, end: full.length });
  }
  return { fullNorm: full, segs };
}

function collectTextIndicesForRange(segs, hitStart, hitEnd) {
  const out = [];
  for (const s of segs) {
    if (s.end > hitStart && s.start < hitEnd) out.push(s.ti);
  }
  return out;
}

function doSearch() {
  const q = normalizeForSearch(searchInput.value);
  matches = [];
  currentMatchIndex = -1;

  document.querySelectorAll('.word-box').forEach(box => {
    box.classList.remove('dim', 'match', 'match-active');
    box.style.display = '';
  });
  document.querySelectorAll('.page-card').forEach(c => c.classList.remove('highlight'));

  if (!q || !data?.pages) {
    matchBadge.textContent = '';
    matchBadge.className = 'match-badge';
    prevBtn.disabled = nextBtn.disabled = true;
    return;
  }

  const matchedKey = new Set();

  data.pages.forEach((page, pageIdx) => {
    const order = readingOrderTextIndices(page);
    const { fullNorm, segs } = buildPageConcatNorm(page, order);
    let pos = 0;
    while (pos <= fullNorm.length - q.length) {
      const hit = fullNorm.indexOf(q, pos);
      if (hit === -1) break;
      const hitEnd = hit + q.length;
      const textIndices = collectTextIndicesForRange(segs, hit, hitEnd);
      const primary = textIndices.length ? textIndices[0] : -1;
      const refText = primary >= 0 ? ((page.texts || [])[primary] || {}).text || '' : '';
      matches.push({ pageIdx, textIndices, textIdx: primary, text: refText });
      textIndices.forEach((ti) => matchedKey.add(`${pageIdx}:${ti}`));
      pos = hit + q.length;
    }
  });

  document.querySelectorAll('.word-box').forEach(box => {
    const page = box.dataset.page;
    const tidx = box.dataset.textIdx;
    const key = `${page}:${tidx}`;
    if (matchedKey.has(key)) {
      box.classList.add('match');
    } else {
      box.classList.add('dim');
    }
  });

  if (matches.length > 0) {
    currentMatchIndex = 0;
    goToMatch(0);
    prevBtn.disabled = nextBtn.disabled = false;
  } else {
    matchBadge.textContent = '검색 결과 없음';
    matchBadge.className = 'match-badge no-results';
    prevBtn.disabled = nextBtn.disabled = true;
  }
}

function goToMatch(idx) {
  if (idx < 0 || idx >= matches.length) return;
  currentMatchIndex = idx;
  const m = matches[idx];

  document.querySelectorAll('.word-box').forEach(b => b.classList.remove('match-active'));
  const indices = m.textIndices && m.textIndices.length
    ? m.textIndices
    : (m.textIdx >= 0 ? [m.textIdx] : []);
  indices.forEach((ti) => {
    const activeBox = document.querySelector(
      `.word-box[data-page="${m.pageIdx}"][data-text-idx="${ti}"]`
    );
    if (activeBox) activeBox.classList.add('match-active');
  });

  const card = document.getElementById(`page-${m.pageIdx}`);
  if (card) {
    document.querySelectorAll('.page-card').forEach(c => c.classList.remove('highlight'));
    card.classList.add('highlight');
    const allActive = card.querySelectorAll('.word-box.match-active');
    if (allActive.length > 0) {
      const boxes = Array.from(allActive);
      boxes.sort((a, b) => {
        const aTop = parseFloat(a.style.top || '0');
        const bTop = parseFloat(b.style.top || '0');
        if (Math.abs(aTop - bTop) > 5) return aTop - bTop;
        return parseFloat(a.style.left || '0') - parseFloat(b.style.left || '0');
      });
      boxes[0].scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
    } else {
      card.scrollIntoView({ behavior: 'smooth', block: 'start', inline: 'nearest' });
    }
  }
  matchBadge.className = 'match-badge has-results';
  matchBadge.innerHTML =
    '<span>' + (idx + 1) + '</span><span class="sep">/</span><span>' + matches.length + '</span>';
}

searchInput.addEventListener('input', () => doSearch());
searchInput.addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    if (e.shiftKey) goToMatch(currentMatchIndex - 1);
    else goToMatch(currentMatchIndex + 1);
  }
});
prevBtn.addEventListener('click', () => goToMatch(currentMatchIndex - 1));
nextBtn.addEventListener('click', () => goToMatch(currentMatchIndex + 1));

(async function initFromToken() {
  const token = new URLSearchParams(window.location.search).get('token');
  if (!token) return;
  content.classList.add('loading');
  content.innerHTML = '<div class="empty-state loading-msg"><p>OCR 결과 불러오는 중…</p></div>';
  try {
    const res = await fetch('/api/session/' + encodeURIComponent(token));
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      const msg = typeof err.detail === 'string' ? err.detail : (res.statusText || '오류');
      throw new Error(msg);
    }
    const session = await res.json();
    data = { pages: session.pages || [] };
    window.__pendingNavHint = session.navigate || null;
    content.classList.remove('loading');
    render();
  } catch (err) {
    content.classList.remove('loading');
    content.innerHTML = '<div class="empty-state"><p class="lead">세션을 불러올 수 없습니다</p><p>' + (err.message || String(err)) + '</p></div>';
  }
})();
