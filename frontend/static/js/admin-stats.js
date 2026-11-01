(function () {
  if (!window.SDApi.isAdmin()) {
    window.location.href = "/login";
    return;
  }

  function showAlert(message, type = "danger") {
    window.SDToast.show(message, type);
  }

  function humanSize(bytes) {
    if (bytes < 1024) return bytes + " B";
    const units = ["KB", "MB", "GB", "TB"];
    let val = bytes;
    for (const u of units) { val /= 1024; if (val < 1024) return val.toFixed(2) + " " + u; }
    return val.toFixed(2) + " PB";
  }

  const SVG_NS = "http://www.w3.org/2000/svg";
  const PALETTE = ["#33478f", "#1f7d54", "#976a1a", "#b3413c", "#9b6bd6", "#2a9d9d", "#d67ab1", "#8a8f98", "#5b6472"];

  function el(tag, attrs) {
    const node = document.createElementNS(SVG_NS, tag);
    for (const k in attrs) node.setAttribute(k, attrs[k]);
    return node;
  }

  // ---- Pie chart (reused for storage usage + file extensions) ----
  function renderPieChart(svgEl, slices) {
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);
    const cx = 100, cy = 100, r = 90;
    const total = slices.reduce((sum, s) => sum + s.value, 0) || 1;
    let startAngle = -Math.PI / 2;

    if (slices.every((s) => s.value === 0)) {
      svgEl.appendChild(el("circle", { cx, cy, r, fill: "var(--surface-2)" }));
      return;
    }

    slices.forEach((slice, i) => {
      const fraction = slice.value / total;
      const endAngle = startAngle + fraction * 2 * Math.PI;
      const x1 = cx + r * Math.cos(startAngle), y1 = cy + r * Math.sin(startAngle);
      const x2 = cx + r * Math.cos(endAngle), y2 = cy + r * Math.sin(endAngle);
      const largeArc = fraction > 0.5 ? 1 : 0;
      let d;
      if (fraction >= 0.9999) {
        const midAngle = startAngle + Math.PI;
        const xm = cx + r * Math.cos(midAngle), ym = cy + r * Math.sin(midAngle);
        d = `M ${x1} ${y1} A ${r} ${r} 0 1 1 ${xm} ${ym} A ${r} ${r} 0 1 1 ${x1} ${y1} Z`;
      } else {
        d = `M ${cx} ${cy} L ${x1} ${y1} A ${r} ${r} 0 ${largeArc} 1 ${x2} ${y2} Z`;
      }
      svgEl.appendChild(el("path", { d, fill: slice.color || PALETTE[i % PALETTE.length] }));
      startAngle = endAngle;
    });
  }

  function renderLegend(containerEl, slices) {
    containerEl.innerHTML = "";
    slices.forEach((slice, i) => {
      const row = document.createElement("div");
      row.className = "flex items-center gap-1 mb-1";
      const swatch = document.createElement("span");
      swatch.style.cssText = `display:inline-block;width:12px;height:12px;border-radius:3px;background:${slice.color || PALETTE[i % PALETTE.length]}`;
      const text = document.createElement("span");
      text.className = "small";
      text.textContent = `${slice.label}: ${slice.display}`;
      row.appendChild(swatch);
      row.appendChild(text);
      containerEl.appendChild(row);
    });
  }

  // ---- Grouped bar chart (uploads vs downloads over time) ----
  function renderBarChart(svgEl, buckets) {
    while (svgEl.firstChild) svgEl.removeChild(svgEl.firstChild);

    const padding = { top: 14, right: 16, bottom: 34, left: 42 };
    const groupWidth = 34;
    const chartWidth = Math.max(buckets.length * groupWidth + padding.left + padding.right, 560);
    const chartHeight = 240;
    const plotHeight = chartHeight - padding.top - padding.bottom;

    svgEl.setAttribute("viewBox", `0 0 ${chartWidth} ${chartHeight}`);
    svgEl.setAttribute("width", chartWidth);
    svgEl.setAttribute("height", chartHeight);

    const maxValue = Math.max(1, ...buckets.map((b) => Math.max(b.uploads, b.downloads)));
    const niceMax = maxValue <= 5 ? 5 : Math.ceil(maxValue / 5) * 5;

    // gridlines + y-axis labels
    for (let i = 0; i <= 4; i++) {
      const value = Math.round((niceMax / 4) * i);
      const y = padding.top + plotHeight - (plotHeight * i) / 4;
      svgEl.appendChild(el("line", {
        x1: padding.left, x2: chartWidth - padding.right, y1: y, y2: y,
        class: "chart-axis-line",
      }));
      const label = el("text", { x: padding.left - 8, y: y + 3, "text-anchor": "end", class: "chart-bar-label" });
      label.textContent = value;
      svgEl.appendChild(label);
    }

    const labelEvery = Math.max(1, Math.ceil(buckets.length / 15));
    const barWidth = 12;

    buckets.forEach((bucket, i) => {
      const groupX = padding.left + i * groupWidth;
      const uploadHeight = (bucket.uploads / niceMax) * plotHeight;
      const downloadHeight = (bucket.downloads / niceMax) * plotHeight;

      const uploadBar = el("rect", {
        x: groupX + 3, y: padding.top + plotHeight - uploadHeight, width: barWidth, height: Math.max(uploadHeight, 0),
        fill: "#33478f", rx: 2,
      });
      const downloadBar = el("rect", {
        x: groupX + 3 + barWidth + 2, y: padding.top + plotHeight - downloadHeight, width: barWidth, height: Math.max(downloadHeight, 0),
        fill: "#1f7d54", rx: 2,
      });
      const title1 = el("title", {});
      title1.textContent = `${bucket.label}: ${bucket.uploads} uploads`;
      uploadBar.appendChild(title1);
      const title2 = el("title", {});
      title2.textContent = `${bucket.label}: ${bucket.downloads} downloads`;
      downloadBar.appendChild(title2);

      svgEl.appendChild(uploadBar);
      svgEl.appendChild(downloadBar);

      if (i % labelEvery === 0) {
        const label = el("text", {
          x: groupX + groupWidth / 2, y: chartHeight - padding.bottom + 16,
          "text-anchor": "middle", class: "chart-bar-label",
        });
        label.textContent = bucket.label.length > 7 ? bucket.label.slice(5) : bucket.label;
        svgEl.appendChild(label);
      }
    });

    svgEl.appendChild(el("line", {
      x1: padding.left, x2: padding.left, y1: padding.top, y2: padding.top + plotHeight, class: "chart-axis-line",
    }));
  }

  async function loadActivity(range) {
    let data;
    try {
      data = await window.SDApi.get(`/api/admin/stats/timeseries?range=${range}`);
    } catch (e) {
      showAlert(e.message);
      return;
    }
    renderBarChart(document.getElementById("activityChart"), data.buckets);
  }

  document.getElementById("rangeSelect").addEventListener("change", (e) => loadActivity(e.target.value));

  function statCard(label, value) {
    const card = document.createElement("div");
    card.className = "card mb-0";
    const val = document.createElement("div");
    val.style.cssText = "font-size:1.8rem; font-weight:700";
    val.textContent = value;
    const lbl = document.createElement("div");
    lbl.className = "text-muted small";
    lbl.textContent = label;
    card.appendChild(val);
    card.appendChild(lbl);
    return card;
  }

  async function load() {
    let s;
    try {
      s = await window.SDApi.get("/api/admin/stats");
    } catch (e) {
      showAlert(e.message);
      return;
    }

    const cards = document.getElementById("statCards");
    cards.innerHTML = "";
    cards.appendChild(statCard("Active files", s.active_files));
    cards.appendChild(statCard("Total uploads (all-time)", s.total_uploads));
    cards.appendChild(statCard("Total downloads (all-time)", s.total_downloads));
    cards.appendChild(statCard("Registered users", s.total_users));

    const used = s.storage_used_bytes;
    const free = Math.max(s.storage_cap_bytes - used, 0);
    const pct = s.storage_cap_bytes > 0 ? ((used / s.storage_cap_bytes) * 100).toFixed(1) : "0";
    const storageSlices = [
      { label: "Used", value: used, display: humanSize(used), color: "#33478f" },
      { label: "Free", value: free, display: humanSize(free), color: "#3b4453" },
    ];
    renderPieChart(document.getElementById("storagePie"), storageSlices);
    renderLegend(document.getElementById("storageLegend"), storageSlices);
    document.getElementById("storageText").textContent =
      `${humanSize(used)} used of ${humanSize(s.storage_cap_bytes)} cap (${pct}%).`;

    const extSlices = (s.extension_breakdown || []).map((e, i) => ({
      label: e.extension, value: e.count, display: `${e.count} file${e.count === 1 ? "" : "s"}`, color: PALETTE[i % PALETTE.length],
    }));
    renderPieChart(document.getElementById("extensionPie"), extSlices.length ? extSlices : [{ label: "None", value: 1, color: "#3b4453" }]);
    renderLegend(document.getElementById("extensionLegend"), extSlices.length ? extSlices : [{ label: "No active files", display: "", color: "#3b4453" }]);

    const eventsBody = document.getElementById("eventsTableBody");
    eventsBody.innerHTML = "";
    const rows = [
      ["Files burned after download", s.total_burned],
      ["Files auto-expired", s.total_expired_events],
      ["Files manually deleted", s.total_deleted_events],
      ["Files pending cleanup (expired, not yet purged)", s.active_files_pending_cleanup],
      ["Total bytes stored (active files)", humanSize(s.active_bytes)],
    ];
    for (const [label, value] of rows) {
      const tr = document.createElement("tr");
      const th = document.createElement("td");
      th.textContent = label;
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(th);
      tr.appendChild(td);
      eventsBody.appendChild(tr);
    }
  }

  load();
  loadActivity("30d");
})();
