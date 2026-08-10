// Two d3 "islands" for the dashboard. Section fragments (loaded via htmx) call
// initRitmo(data) / initMuro(data) with their slice of the cached payload.

const MES = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

// Wire an element's hover to the shared floating tooltip.
function bindTip(el, tip, buildHTML) {
  el.addEventListener("mouseenter", () => {
    tip.innerHTML = buildHTML();
    tip.style.display = "flex";
  });
  el.addEventListener("mousemove", (e) => {
    tip.style.left = e.clientX + 14 + "px";
    tip.style.top = e.clientY + 14 + "px";
  });
  el.addEventListener("mouseleave", () => (tip.style.display = "none"));
}

// ---- Your Rhythm: ridgeline (hour x weekday) with hover showing the cover ----
function initRitmo(D) {
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const heat = D.heat,
    top = D.heat_top;
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.getElementById("ridge");
  if (!svg) return;
  const leftPad = 70,
    topPad = 30,
    W = 820,
    plotW = W - leftPad - 30;
  const rowGap = 50,
    amp = 56;
  const xAt = (h) => leftPad + (h / 23) * plotW;
  const baseAt = (d) => topPad + d * rowGap + amp;
  const nz = heat
    .flat()
    .filter((v) => v > 0)
    .sort((a, b) => a - b);
  const scaleMax = nz[Math.floor(nz.length * 0.95)] || 1;
  const hgt = (v) => Math.min(v / scaleMax, 1) * amp;

  function ridgePath(vals, base) {
    const pts = vals.map((v, h) => [xAt(h), base - hgt(v)]);
    let d = `M ${pts[0][0]} ${base} L ${pts[0][0]} ${pts[0][1]}`;
    for (let i = 0; i < pts.length - 1; i++) {
      const p0 = pts[i - 1] || pts[i],
        p1 = pts[i],
        p2 = pts[i + 1],
        p3 = pts[i + 2] || p2;
      d += ` C ${p1[0] + (p2[0] - p0[0]) / 6} ${p1[1] + (p2[1] - p0[1]) / 6} ${p2[0] - (p3[0] - p1[0]) / 6} ${p2[1] - (p3[1] - p1[1]) / 6} ${p2[0]} ${p2[1]}`;
    }
    d += ` L ${pts[pts.length - 1][0]} ${base} Z`;
    return d;
  }

  [0, 6, 12, 18, 23].forEach((h) => {
    const t = document.createElementNS(NS, "text");
    t.setAttribute("x", xAt(h));
    t.setAttribute("y", topPad + 6 * rowGap + amp + 22);
    t.setAttribute("text-anchor", "middle");
    t.setAttribute("fill", "#666");
    t.setAttribute("font-family", "Space Grotesk");
    t.setAttribute("font-size", "12");
    t.textContent = h + "h";
    svg.appendChild(t);
  });

  for (let d = 0; d < 7; d++) {
    const base = baseAt(d);
    const path = document.createElementNS(NS, "path");
    path.setAttribute("d", ridgePath(heat[d], base));
    path.setAttribute("fill", "#123a20");
    path.setAttribute("stroke", "#1DB954");
    path.setAttribute("stroke-width", "2.5");
    svg.appendChild(path);
    const lbl = document.createElementNS(NS, "text");
    lbl.setAttribute("x", leftPad - 14);
    lbl.setAttribute("y", base - 4);
    lbl.setAttribute("text-anchor", "end");
    lbl.setAttribute("fill", "#aaa");
    lbl.setAttribute("font-family", "Space Grotesk");
    lbl.setAttribute("font-size", "13");
    lbl.textContent = days[d];
    svg.appendChild(lbl);
  }

  const tip = document.getElementById("tip");
  for (let d = 0; d < 7; d++) {
    const base = baseAt(d);
    for (let h = 0; h < 24; h++) {
      const v = heat[d][h];
      if (v === 0) continue;
      const info = top[d][h];
      const c = document.createElementNS(NS, "circle");
      c.setAttribute("cx", xAt(h));
      c.setAttribute("cy", base - hgt(v));
      c.setAttribute("r", "8");
      c.setAttribute("fill", "transparent");
      c.style.cursor = "pointer";
      bindTip(
        c,
        tip,
        () =>
          (info && info.art
            ? `<img src="${info.art}" style="width:56px;height:56px;object-fit:cover;border:2px solid #fff">`
            : "") +
          `<div><div class="head text-spotify" style="font-size:13px">${days[d]} ${h}:00 · ${v} plays</div>` +
          `<div style="font-size:12px;color:#ddd">${info ? info.label : ""}</div></div>`,
      );
      svg.appendChild(c);
    }
  }
}

// ---- Cover Wall: treemap with a month slider (tiles grow/shrink in place) ----
function initMuro(D) {
  const mo = document.getElementById("mosaic");
  if (!mo) return;
  const tip = document.getElementById("tip");
  const albums = D.top_albums.slice(0, 28);
  const monthsList = D.plays_per_month.map((x) => x.month);
  const NMON = monthsList.length;
  let pos = NMON; // continuous position 0..NMON, starts at all-time
  const fmtMonth = (ym) => {
    const [y, m] = ym.split("-");
    return MES[+m - 1] + " " + y.slice(2);
  };
  const cumPlays = (al, p) => {
    if (!al.monthly) return 0;
    let s = 0;
    for (let j = 0; j < NMON; j++)
      s += (al.monthly[monthsList[j]] || 0) * Math.max(0, Math.min(1, p - j));
    return s;
  };

  const root = d3
    .hierarchy({ children: albums })
    .sum((d) => d.plays)
    .sort((a, b) => b.value - a.value);
  const layout = d3.treemap().tile(d3.treemapResquarify).paddingInner(3);

  albums.forEach((al) => {
    const t = document.createElement("div");
    t.className = "absolute overflow-hidden";
    t.style.transition = "opacity .3s ease";
    t.style.backgroundImage = `url('${al.art}')`;
    t.style.backgroundSize = "cover";
    t.style.backgroundPosition = "center";
    t.style.cursor = "pointer";
    bindTip(
      t,
      tip,
      () =>
        `<img src="${al.art}" style="width:220px;height:220px;object-fit:contain;background:#000;border:2px solid #fff">` +
        `<div><div class="head text-spotify" style="font-size:13px">${Math.round(cumPlays(al, pos))} plays</div>` +
        `<div style="font-size:12px;color:#ddd;max-width:160px">${al.album}</div></div>`,
    );
    al._tile = t;
    mo.appendChild(t);
  });

  function redraw() {
    const W = mo.clientWidth,
      H = mo.clientHeight;
    layout.size([W, H]);
    root.sum((d) => cumPlays(d, pos));
    layout(root);
    root.leaves().forEach((leaf) => {
      const t = leaf.data._tile;
      const w = leaf.x1 - leaf.x0,
        h = leaf.y1 - leaf.y0;
      t.style.left = leaf.x0 + "px";
      t.style.top = leaf.y0 + "px";
      t.style.width = w + "px";
      t.style.height = h + "px";
      t.style.opacity = w > 1 && h > 1 ? "1" : "0";
    });
  }

  const slider = document.getElementById("monthSlider");
  const mlabel = document.getElementById("monthLabel");
  slider.min = "0";
  slider.max = String(NMON);
  slider.step = "any";
  slider.value = String(pos);
  const updateLabel = () =>
    (mlabel.textContent =
      "Through " + fmtMonth(monthsList[Math.min(Math.floor(pos), NMON - 1)]));
  slider.addEventListener("input", () => {
    pos = +slider.value;
    updateLabel();
    redraw();
  });
  updateLabel();
  redraw();
  window.addEventListener("resize", redraw);
}
