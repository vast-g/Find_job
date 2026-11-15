/* =============================================================================
 * charts.js —— 手写 SVG 图表库（不引 ECharts / Chart.js）
 *
 * 为什么自己画：
 *   部署机器外网不通，引用任何站外静态库都会让页面直接白屏。图表需求其实只有
 *   环形图 / 条形图 / 柱状图 / 折线图四种，用 SVG 手写完全够用，
 *   还能顺带避开「图表库体积大、主题难统一」的问题。
 *
 * 统一约定：
 *   · 所有函数签名是 Charts.xxx(container, data, opts)，container 可以是元素或选择器。
 *   · 每个图都返回它生成的 SVG 字符串，方便调试与二次利用。
 *   · 用 viewBox + width:100% 实现自适应，不用监听 resize，也不用重绘。
 *   · 数据为空时画空状态，而不是让容器塌成一条线。
 * ========================================================================== */
(function (global) {
  'use strict';

  /** 主题色序：与 css/app.css 的深色主题配套，色相错开保证相邻扇区可分辨 */
  var PALETTE = ['#4f9cf9', '#38d39f', '#f7b955', '#f2637b', '#a78bfa',
    '#22d3ee', '#fb923c', '#84cc16', '#e879f9', '#60a5fa'];

  /** 折线图渐变 id 的自增序号，保证同页多个图表 id 不撞车 */
  var lineSeq = 0;

  function colorAt(i) { return PALETTE[i % PALETTE.length]; }

  /** SVG 里的文本必须转义，否则企业名里的 & < 会直接把图表搞坏 */
  function esc(s) {
    return String(s === null || s === undefined ? '' : s)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
  }

  function resolve(el) {
    return typeof el === 'string' ? document.querySelector(el) : el;
  }

  /** 统一的空状态：宁可显示「暂无数据」，也不要留下一个空白方块让人以为坏了 */
  function empty(container, text) {
    if (!container) { return ''; }
    var html = '<div class="chart-empty">' + esc(text || '暂无数据') + '</div>';
    container.innerHTML = html;
    return html;
  }

  /** 把 0..1 的占比安全地转成百分比，避免除零得到 NaN 宽度 */
  function ratio(v, total) {
    if (!total || total <= 0) { return 0; }
    var r = v / total;
    return r < 0 ? 0 : (r > 1 ? 1 : r);
  }

  /** 数字缩写：12000 → 1.2万，长数字在图上会挤成一团 */
  function shortNum(n) {
    n = Number(n) || 0;
    if (Math.abs(n) >= 100000000) { return (n / 100000000).toFixed(1) + '亿'; }
    if (Math.abs(n) >= 10000) { return (n / 10000).toFixed(1) + '万'; }
    return String(n);
  }

  var Charts = {
    PALETTE: PALETTE,
    colorAt: colorAt,
    esc: esc,
    shortNum: shortNum,

    /* =========================================================================
     * 环形图：看「构成比例」，中心显示总量
     * items: [{ label, value, color? }]
     * ====================================================================== */
    donut: function (container, items, opts) {
      var el = resolve(container);
      opts = opts || {};
      items = (items || []).filter(function (d) { return Number(d.value) > 0; });

      var total = items.reduce(function (s, d) { return s + Number(d.value); }, 0);
      if (!el) { return ''; }
      if (!items.length || total <= 0) { return empty(el, opts.emptyText || '暂无数据'); }

      var size = opts.size || 180;
      var thickness = opts.thickness || 20;
      var cx = size / 2, cy = size / 2;
      var r = (size - thickness) / 2 - 2;
      var C = 2 * Math.PI * r;          // 周长：用 stroke-dasharray 画扇区

      var offset = 0;
      var arcs = items.map(function (d, i) {
        var frac = ratio(Number(d.value), total);
        var len = frac * C;
        // 留 1.2 的间隙，相邻扇区不会糊在一起
        var gap = items.length > 1 ? 1.2 : 0;
        var seg = '<circle class="donut-seg" cx="' + cx + '" cy="' + cy + '" r="' + r + '"' +
          ' fill="none" stroke="' + esc(d.color || colorAt(i)) + '" stroke-width="' + thickness + '"' +
          ' stroke-dasharray="' + Math.max(len - gap, 0.001) + ' ' + (C - Math.max(len - gap, 0.001)) + '"' +
          ' stroke-dashoffset="' + (-offset) + '" stroke-linecap="butt">' +
          '<title>' + esc(d.label) + '：' + esc(d.value) + '（' + (frac * 100).toFixed(1) + '%）</title>' +
          '</circle>';
        offset += len;
        return seg;
      }).join('');

      var centerValue = opts.centerValue !== undefined ? opts.centerValue : shortNum(total);
      var centerLabel = opts.centerLabel || '总计';

      var svg = '<svg class="chart chart-donut" viewBox="0 0 ' + size + ' ' + size + '"' +
        ' preserveAspectRatio="xMidYMid meet" role="img" aria-label="' + esc(centerLabel) + '">' +
        '<g transform="rotate(-90 ' + cx + ' ' + cy + ')"><circle cx="' + cx + '" cy="' + cy + '" r="' + r +
        '" fill="none" stroke="rgba(255,255,255,.06)" stroke-width="' + thickness + '"/>' + arcs + '</g>' +
        '<text class="donut-center-value" x="' + cx + '" y="' + (cy + 2) + '" text-anchor="middle">' + esc(centerValue) + '</text>' +
        '<text class="donut-center-label" x="' + cx + '" y="' + (cy + 22) + '" text-anchor="middle">' + esc(centerLabel) + '</text>' +
        '</svg>';

      // 图例用 HTML 排版：文字换行、对齐比 SVG <text> 好控制得多
      var legend = '<ul class="chart-legend">' + items.map(function (d, i) {
        var pct = (ratio(Number(d.value), total) * 100).toFixed(1);
        return '<li><span class="dot" style="background:' + esc(d.color || colorAt(i)) + '"></span>' +
          '<span class="lg-label" title="' + esc(d.label) + '">' + esc(d.label) + '</span>' +
          '<span class="lg-value">' + esc(d.value) + '<em>' + pct + '%</em></span></li>';
      }).join('') + '</ul>';

      el.innerHTML = '<div class="chart-donut-wrap">' + svg + legend + '</div>';
      return svg;
    },

    /* =========================================================================
     * 横向条形图：看 TOP N 排名（例如城市岗位数）
     * ====================================================================== */
    hbars: function (container, items, opts) {
      var el = resolve(container);
      opts = opts || {};
      items = (items || []).slice(0, opts.limit || 8);

      if (!el) { return ''; }
      if (!items.length) { return empty(el, opts.emptyText || '暂无数据'); }

      var rowH = 26;
      var W = 460;
      var labelW = opts.labelWidth || 88;   // 左侧文字留白
      var valueW = 46;                      // 右侧数值留白
      var barMax = W - labelW - valueW;
      var H = items.length * rowH + 6;
      var max = items.reduce(function (m, d) { return Math.max(m, Number(d.value) || 0); }, 0) || 1;

      var rows = items.map(function (d, i) {
        var v = Number(d.value) || 0;
        var w = Math.max(ratio(v, max) * barMax, v > 0 ? 3 : 0);  // 极小值也留 3px，看得见
        var y = i * rowH + 6;
        var barY = y + 4;
        return '<g class="hbar-row">' +
          '<text class="hbar-label" x="0" y="' + (barY + 11) + '">' + esc(d.label) + '</text>' +
          '<rect class="hbar-track" x="' + labelW + '" y="' + barY + '" width="' + barMax + '" height="12" rx="6"/>' +
          '<rect class="hbar-bar" x="' + labelW + '" y="' + barY + '" width="' + w.toFixed(1) + '" height="12" rx="6"' +
          ' fill="' + esc(d.color || colorAt(i)) + '">' +
          '<title>' + esc(d.label) + '：' + esc(v) + '</title></rect>' +
          '<text class="hbar-value" x="' + (W - 2) + '" y="' + (barY + 11) + '" text-anchor="end">' + esc(shortNum(v)) + '</text>' +
          '</g>';
      }).join('');

      var svg = '<svg class="chart chart-hbars" viewBox="0 0 ' + W + ' ' + H + '"' +
        ' preserveAspectRatio="xMidYMid meet" role="img">' + rows + '</svg>';
      el.innerHTML = svg;
      return svg;
    },

    /* =========================================================================
     * 柱状图：看区间分布（例如薪资区间）
     * ====================================================================== */
    columns: function (container, items, opts) {
      var el = resolve(container);
      opts = opts || {};
      items = items || [];

      if (!el) { return ''; }
      if (!items.length) { return empty(el, opts.emptyText || '暂无数据'); }

      var W = 460, H = opts.height || 190;
      var padL = 8, padR = 8, padT = 18, padB = 34;   // 顶部留给数值、底部留给类目名
      var plotH = H - padT - padB;
      var n = items.length;
      var slot = (W - padL - padR) / n;
      var barW = Math.min(slot * 0.56, 46);
      var max = items.reduce(function (m, d) { return Math.max(m, Number(d.value) || 0); }, 0) || 1;

      // 3 条水平参考线，让高度差更容易读
      var grid = [0, 0.5, 1].map(function (t) {
        var y = padT + plotH * t;
        return '<line class="grid-line" x1="' + padL + '" y1="' + y + '" x2="' + (W - padR) + '" y2="' + y + '"/>';
      }).join('');

      var bars = items.map(function (d, i) {
        var v = Number(d.value) || 0;
        var h = Math.max(ratio(v, max) * plotH, v > 0 ? 3 : 0);
        var x = padL + slot * i + (slot - barW) / 2;
        var y = padT + plotH - h;
        return '<g class="col-group">' +
          '<rect class="col-bar" x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" width="' + barW.toFixed(1) +
          '" height="' + h.toFixed(1) + '" rx="4" fill="' + esc(d.color || colorAt(i)) + '">' +
          '<title>' + esc(d.label) + '：' + esc(v) + '</title></rect>' +
          '<text class="col-value" x="' + (x + barW / 2).toFixed(1) + '" y="' + (y - 5).toFixed(1) + '" text-anchor="middle">' +
          esc(shortNum(v)) + '</text>' +
          '<text class="col-label" x="' + (x + barW / 2).toFixed(1) + '" y="' + (H - padB + 16) + '" text-anchor="middle">' +
          esc(d.label) + '</text>' +
          '</g>';
      }).join('');

      var svg = '<svg class="chart chart-columns" viewBox="0 0 ' + W + ' ' + H + '"' +
        ' preserveAspectRatio="xMidYMid meet" role="img">' + grid + bars + '</svg>';
      el.innerHTML = svg;
      return svg;
    },

    /* =========================================================================
     * 折线/面积图：看趋势（例如每次 AI 请求的耗时）
     * opts: { labels?, height?, color?, area? }
     * ====================================================================== */
    line: function (container, values, opts) {
      var el = resolve(container);
      opts = opts || {};
      values = (values || []).map(Number).filter(function (v) { return !isNaN(v); });

      if (!el) { return ''; }
      if (values.length < 1) { return empty(el, opts.emptyText || '暂无数据'); }

      var W = 460, H = opts.height || 150;
      var padL = 10, padR = 10, padT = 16, padB = 24;
      var plotW = W - padL - padR, plotH = H - padT - padB;

      var max = Math.max.apply(null, values);
      var min = Math.min.apply(null, values);
      if (max === min) { max = min + 1; }        // 全等值时给个高度，避免除以 0

      var stepX = values.length > 1 ? plotW / (values.length - 1) : 0;
      var pts = values.map(function (v, i) {
        var x = padL + stepX * i;
        var y = padT + plotH - ratio(v - min, max - min) * plotH;
        return [x, y];
      });

      var color = opts.color || PALETTE[0];
      var d = pts.map(function (p, i) { return (i ? 'L' : 'M') + p[0].toFixed(1) + ' ' + p[1].toFixed(1); }).join(' ');
      var areaD = d + ' L' + pts[pts.length - 1][0].toFixed(1) + ' ' + (padT + plotH) +
        ' L' + pts[0][0].toFixed(1) + ' ' + (padT + plotH) + ' Z';

      var dots = pts.map(function (p, i) {
        return '<circle class="line-dot" cx="' + p[0].toFixed(1) + '" cy="' + p[1].toFixed(1) + '" r="2.6" fill="' + esc(color) + '">' +
          '<title>' + esc((opts.labels && opts.labels[i]) || ('#' + (i + 1))) + '：' + esc(values[i]) +
          (opts.unit ? esc(opts.unit) : '') + '</title></circle>';
      }).join('');

      // 渐变 id 必须每次唯一且被下面正确引用：同一页面可能有多个折线图，
      // id 重复会导致后面的图错用前面的渐变。
      var gradId = 'jobweb-line-grad-' + (lineSeq++);
      var svg = '<svg class="chart chart-line" viewBox="0 0 ' + W + ' ' + H + '"' +
        ' preserveAspectRatio="none" role="img">' +
        '<defs><linearGradient id="' + gradId + '" x1="0" y1="0" x2="0" y2="1">' +
        '<stop offset="0%" stop-color="' + esc(color) + '" stop-opacity="0.35"/>' +
        '<stop offset="100%" stop-color="' + esc(color) + '" stop-opacity="0"/>' +
        '</linearGradient></defs>' +
        (opts.area === false ? '' : '<path d="' + areaD + '" fill="url(#' + gradId + ')" opacity="0.5"/>') +
        '<path class="line-path" d="' + d + '" fill="none" stroke="' + esc(color) + '" stroke-width="2" ' +
        'stroke-linejoin="round" stroke-linecap="round"/>' + dots +
        '<text class="line-max" x="' + padL + '" y="' + (padT - 4) + '">' + esc(shortNum(max)) + '</text>' +
        '<text class="line-min" x="' + padL + '" y="' + (H - 6) + '">' + esc(shortNum(min)) + '</text>' +
        '</svg>';

      el.innerHTML = svg;
      return svg;
    },

    /* =========================================================================
     * 进度环：单个比例（健康度/完成度）
     * ====================================================================== */
    ring: function (container, percent, opts) {
      var el = resolve(container);
      opts = opts || {};
      if (!el) { return ''; }

      percent = Math.max(0, Math.min(100, Number(percent) || 0));
      var size = opts.size || 96, thickness = opts.thickness || 9;
      var cx = size / 2, cy = size / 2, r = (size - thickness) / 2 - 1;
      var C = 2 * Math.PI * r;
      var dash = ratio(percent, 100) * C;

      var svg = '<svg class="chart chart-ring" viewBox="0 0 ' + size + ' ' + size + '" role="img">' +
        '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="rgba(255,255,255,.08)" stroke-width="' + thickness + '"/>' +
        '<circle cx="' + cx + '" cy="' + cy + '" r="' + r + '" fill="none" stroke="' + esc(opts.color || PALETTE[1]) + '"' +
        ' stroke-width="' + thickness + '" stroke-linecap="round" stroke-dasharray="' + dash.toFixed(1) + ' ' + (C - dash).toFixed(1) + '"' +
        ' transform="rotate(-90 ' + cx + ' ' + cy + ')"/>' +
        '<text class="ring-value" x="' + cx + '" y="' + (cy + 5) + '" text-anchor="middle">' + esc(Math.round(percent)) + '%</text>' +
        '</svg>';
      el.innerHTML = svg;
      return svg;
    }
  };

  global.Charts = Charts;
})(window);
