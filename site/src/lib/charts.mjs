/**
 * Build-time chart rendering for PRISM-R.
 *
 * Each function reads the processed pipeline JSON and returns an SVG string,
 * rendered with Observable Plot against a linkedom document. Charts are
 * generated when the Astro site builds; nothing runs in the browser.
 *
 * Three charts:
 *   renderCascade        the road-to-remand RRI cascade (rri.json)
 *   renderDisproportion  child population vs custodial remand, by ethnicity
 *   renderRemandMix      remand decision mix by ethnicity
 */
import { readFileSync } from "node:fs";
import * as Plot from "@observablehq/plot";
import { parseHTML } from "linkedom";

const PROCESSED = new URL("../../../data/processed/", import.meta.url);

function load(name) {
  return JSON.parse(readFileSync(new URL(name, PROCESSED), "utf-8"));
}

/** Render a Plot specification to an SVG string. */
function render(spec) {
  const { document } = parseHTML("<!DOCTYPE html><html><body></body></html>");
  const node = Plot.plot({ ...spec, document });
  return node.outerHTML;
}

const FONT = "'Source Serif 4', Georgia, serif";
const UI_FONT = "Inter, system-ui, sans-serif";

// Cascade design. The plot area is 560 x 260; an RRI of 0.5 sits at y 260 and
// 2.5 at y 0. Colours and emphasis tints follow the agreed reference design.
const CASCADE_STAGES = ["Stop and search", "Arrest", "Remand", "Custodial sentence"];
const CASCADE_DECISIONS = ["stop_search", "arrest", "remand", "custodial_sentence"];
const CASCADE_X = [0, 187, 374, 560];
const CASCADE_LINE = {
  Black: { colour: "#534AB7", emphasis: "#3C3489", width: 2.5, radius: 4 },
  Mixed: { colour: "#D85A30", emphasis: "#D85A30", width: 2.5, radius: 4 },
  Asian: { colour: "#1D9E75", emphasis: "#0F6E56", width: 2.5, radius: 4 },
  Other: { colour: "#888780", emphasis: "#888780", width: 2, radius: 3.5 },
};
const CASCADE_DRAW_ORDER = ["Black", "Mixed", "Asian", "Other"];
const CASCADE_LABELLED = ["Black", "Asian"];

const cascadeY = (rri) => 260 - (rri - 0.5) * 130;


// --------------------------------------------------------------------------
// Chart A: the road-to-remand cascade
//
// An opinionated, hand-built inline SVG, rather than an Observable Plot
// chart, generated at build time from rri.json. The plot geometry follows
// the agreed reference design.
// --------------------------------------------------------------------------
export function renderCascade() {
  const rri = load("rri.json").records;

  // value[ethnicity][stageIndex] = RRI. Custodial sentencing uses the
  // three-year pooled estimate.
  const value = {};
  for (const record of rri) {
    if (record.provenance !== "prism_r_derived") continue;
    const stage = CASCADE_DECISIONS.indexOf(record.decision_point);
    if (stage < 0) continue;
    if (record.decision_point === "custodial_sentence" && !record.pooled) continue;
    if (!CASCADE_LINE[record.ethnicity]) continue;
    (value[record.ethnicity] ??= {})[stage] = record.rri;
  }

  // Data-driven lines and markers.
  let lines = "";
  for (const ethnicity of CASCADE_DRAW_ORDER) {
    const cfg = CASCADE_LINE[ethnicity];
    const points = CASCADE_X
      .map((x, i) => `${x},${cascadeY(value[ethnicity][i]).toFixed(1)}`)
      .join(" ");
    const dots = CASCADE_X
      .map(
        (x, i) =>
          `<circle cx="${x}" cy="${cascadeY(value[ethnicity][i]).toFixed(1)}" ` +
          `r="${cfg.radius}" fill="${cfg.colour}"/>`,
      )
      .join("");
    lines +=
      `<polyline points="${points}" fill="none" stroke="${cfg.colour}" ` +
      `stroke-width="${cfg.width}" stroke-linecap="round" stroke-linejoin="round"/>` +
      dots;
  }

  // Emphasised endpoint labels for Black and Asian, in a darker line tint.
  let endLabels = "";
  for (const ethnicity of CASCADE_LABELLED) {
    const cfg = CASCADE_LINE[ethnicity];
    const left = value[ethnicity][0];
    const right = value[ethnicity][3];
    endLabels +=
      `<text x="-9" y="${cascadeY(left).toFixed(1)}" text-anchor="end" ` +
      `dominant-baseline="middle" fill="${cfg.emphasis}">${left.toFixed(2)}</text>` +
      `<text x="569" y="${cascadeY(right).toFixed(1)}" text-anchor="start" ` +
      `dominant-baseline="middle" fill="${cfg.emphasis}">${right.toFixed(2)}</text>`;
  }

  const yTicks = [
    [0.5, 260], [1.0, 195], [1.5, 130], [2.0, 65], [2.5, 0],
  ]
    .map(
      ([v, y]) =>
        `<text x="-10" y="${y}" text-anchor="end" dominant-baseline="middle">` +
        `${v.toFixed(1)}</text>`,
    )
    .join("");
  const xLabels = CASCADE_STAGES.map(
    (stage, i) => `<text x="${CASCADE_X[i]}" y="285">${stage}</text>`,
  ).join("");

  const svg = `<svg viewBox="0 0 680 360" width="100%" role="img" aria-labelledby="cascade-title-svg" style="font-family:${UI_FONT}">
<title id="cascade-title-svg">Road-to-remand cascade: Relative Rate Index by ethnicity across four decision points</title>
<g transform="translate(70,30)">
<line x1="0" y1="0" x2="0" y2="260" stroke="#D3D1C7" stroke-width="0.5"/>
<line x1="0" y1="260" x2="560" y2="260" stroke="#D3D1C7" stroke-width="0.5"/>
<g stroke="#F1EFE8" stroke-width="0.5">
<line x1="0" y1="0" x2="560" y2="0"/>
<line x1="0" y1="65" x2="560" y2="65"/>
<line x1="0" y1="130" x2="560" y2="130"/>
<line x1="0" y1="260" x2="560" y2="260"/>
</g>
<g font-size="11" fill="#888780">${yTicks}</g>
<line x1="0" y1="195" x2="560" y2="195" stroke="#888780" stroke-width="1" stroke-dasharray="4 4"/>
<text x="555" y="190" text-anchor="end" font-size="10.5" fill="#5F5E5A">White baseline (1.0)</text>
<g font-size="12" fill="#444441" text-anchor="middle">${xLabels}</g>
<g>${lines}</g>
<g font-size="11.5" font-weight="500">${endLabels}</g>
</g>
</svg>`;

  return `<figure class="cascade">
<p class="cascade-title">The road to remand: relative rate by ethnicity, four decision points</p>
<p class="cascade-subtitle">Children aged 10 to 17, England and Wales, year ending March 2025. An RRI of 1.0 represents parity with White children.</p>
<ul class="cascade-legend">
<li><span class="sw" style="background:#534AB7"></span>Black</li>
<li><span class="sw" style="background:#D85A30"></span>Mixed</li>
<li><span class="sw" style="background:#1D9E75"></span>Asian</li>
<li><span class="sw" style="background:#888780"></span>Other</li>
<li><span class="sw sw-baseline"></span>White baseline</li>
</ul>
${svg}
<p class="cascade-finding">The four groups do not follow one pattern. For Black children the disparity is widest at the first point of contact, a stop and search rate 2.40 times the White rate, and is lower at each later stage. For Asian children it runs the other way, from below parity at the policing stages to above it at the court. On these figures, much of the measured disparity is present before a child reaches the court.</p>
<p class="caption">PRISM-R analysis. Stop and search and arrest computed from Home Office Police powers and procedures, year ending March 2025. Remand and the pooled custodial sentencing estimate computed from YJB Youth Justice Statistics 2024-25. Retrieved May 2026. <a href="/data/manifest.json">See the build manifest</a>.</p>
</figure>`;
}


// --------------------------------------------------------------------------
// Chart B: child population vs custodial remand, by ethnicity
// --------------------------------------------------------------------------
export function renderDisproportion() {
  const populations = load("populations.json").records;
  const remand = load("remand_outcomes.json").records;
  const groups = ["White", "Black", "Asian", "Mixed", "Other"];

  const population = Object.fromEntries(groups.map((g) => [g, 0]));
  for (const record of populations) {
    if (record.population != null && groups.includes(record.ethnicity)) {
      population[record.ethnicity] += record.population;
    }
  }
  const populationTotal = groups.reduce((s, g) => s + population[g], 0);

  const ydp = Object.fromEntries(groups.map((g) => [g, 0]));
  for (const record of remand) {
    if (
      record.year === 2025 &&
      record.breakdown === "ethnicity" &&
      record.remand_type === "ydp" &&
      groups.includes(record.ethnicity) &&
      record.count != null
    ) {
      ydp[record.ethnicity] += record.count;
    }
  }
  const ydpTotal = groups.reduce((s, g) => s + ydp[g], 0);

  const rows = [];
  for (const g of groups) {
    rows.push({
      ethnicity: g,
      measure: "Share of child population",
      share: (population[g] / populationTotal) * 100,
    });
    rows.push({
      ethnicity: g,
      measure: "Share of custodial remand",
      share: (ydp[g] / ydpTotal) * 100,
    });
  }

  return render({
    width: 680,
    height: 420,
    marginTop: 28,
    marginLeft: 48,
    marginRight: 20,
    marginBottom: 56,
    style: { fontFamily: FONT, fontSize: "13px", background: "transparent" },
    x: { axis: null, paddingOuter: 0.1 },
    fx: { domain: groups, label: null, tickSize: 0 },
    y: { domain: [0, 80], label: "Share (%)", grid: true, ticks: 5 },
    color: {
      domain: ["Share of child population", "Share of custodial remand"],
      range: ["#aab4bf", "#1f3a5f"],
      legend: true,
    },
    marks: [
      Plot.barY(rows, { fx: "ethnicity", x: "measure", y: "share", fill: "measure" }),
      Plot.text(rows, {
        fx: "ethnicity",
        x: "measure",
        y: "share",
        text: (d) => d.share.toFixed(1) + "%",
        dy: -9,
        fontSize: 11.5,
        fontWeight: 600,
        fill: "#1a1a1a",
      }),
      Plot.ruleY([0], { stroke: "#999" }),
    ],
  });
}


// --------------------------------------------------------------------------
// Chart C: remand decision mix by ethnicity
// --------------------------------------------------------------------------
export function renderRemandMix() {
  const remand = load("remand_outcomes.json").records;
  // Other and Unknown are omitted: one RLAA cell for Other is disclosure
  // suppressed, and Unknown is not a YJB ethnic group. See the methods page.
  const groups = ["White", "Asian", "Mixed", "Black"];
  const types = [
    ["bail", "Bail"],
    ["community_remand", "Community remand"],
    ["rlaa", "Remand to local authority accommodation"],
    ["ydp", "Custodial remand"],
  ];
  const typeLabel = Object.fromEntries(types);

  const counts = {};
  for (const record of remand) {
    if (record.year === 2025 && record.breakdown === "ethnicity" &&
        groups.includes(record.ethnicity) && record.count != null) {
      counts[record.ethnicity] ??= {};
      counts[record.ethnicity][record.remand_type] = record.count;
    }
  }

  const rows = [];
  for (const g of groups) {
    const total = types.reduce((s, [t]) => s + (counts[g][t] || 0), 0);
    let cursor = 0;
    for (const [t, label] of types) {
      const pct = ((counts[g][t] || 0) / total) * 100;
      rows.push({
        ethnicity: g,
        type: label,
        pct,
        x1: cursor,
        x2: cursor + pct,
      });
      cursor += pct;
    }
  }

  return render({
    width: 680,
    height: 300,
    marginTop: 28,
    marginLeft: 66,
    marginRight: 20,
    marginBottom: 52,
    style: { fontFamily: FONT, fontSize: "13px", background: "transparent" },
    x: { domain: [0, 100], label: "Share of remand decisions (%)", grid: true, ticks: 5 },
    y: { domain: groups, label: null, tickSize: 0 },
    color: {
      domain: types.map(([, label]) => label),
      range: ["#cdd5db", "#9aa7b4", "#5b7185", "#1f3a5f"],
      legend: true,
    },
    marks: [
      Plot.rect(rows, {
        y: "ethnicity",
        x1: "x1",
        x2: "x2",
        fill: "type",
        inset: 0.5,
      }),
      // Label the custodial remand segment, the policy-relevant share.
      Plot.text(rows.filter((r) => r.type === "Custodial remand"), {
        y: "ethnicity",
        x: (d) => (d.x1 + d.x2) / 2,
        text: (d) => d.pct.toFixed(1) + "%",
        fill: "white",
        fontSize: 11,
        fontWeight: 600,
      }),
    ],
  });
}


// --------------------------------------------------------------------------
// Chart D: static choropleth, stop-and-search RRI for Black children by force
//
// A hand-built inline SVG from force_boundaries.json (simplified ONS police
// force area boundaries) and context_indicators.json. The per-force RRI is
// the Black stop-and-search rate divided by the White rate, both per 1,000
// children in the force area. Sequential ramp, light grey near parity to
// deep slate at an RRI of 3 or more.
// --------------------------------------------------------------------------
const CHORO_LOW = [0xe4, 0xe4, 0xe0];   // near parity
const CHORO_HIGH = [0x1b, 0x3a, 0x5f];  // RRI 3.0 and above, the wordmark slate
const CHORO_MIN = 1.0;
const CHORO_MAX = 3.0;

function choroplethColour(rri) {
  const t = Math.min(1, Math.max(0, (rri - CHORO_MIN) / (CHORO_MAX - CHORO_MIN)));
  const channel = (i) =>
    Math.round(CHORO_LOW[i] + (CHORO_HIGH[i] - CHORO_LOW[i]) * t);
  return `rgb(${channel(0)},${channel(1)},${channel(2)})`;
}

export function renderForceChoropleth() {
  const boundaries = load("force_boundaries.json").records;
  const context = load("context_indicators.json").records;

  // Per-force Black and White stop-and-search rates -> RRI. A force whose
  // Black or White cell is suppressed (search count below the disclosure
  // threshold) gets no RRI: its rate derives from a sub-6 count, so shading
  // it would display what the suppression module protects.
  const rates = {};
  const suppressed = new Set();
  for (const r of context) {
    if (r.indicator !== "stop_search_rate" || r.breakdown !== "by_ethnicity") continue;
    if (r.ethnicity !== "Black" && r.ethnicity !== "White") continue;
    if (r.suppressed === true || r.disclosure_status === "source_suppressed") {
      suppressed.add(r.geo_id);
      continue;
    }
    (rates[r.geo_id] ??= {})[r.ethnicity] = r.rate_per_1000;
  }
  const rriOf = {};
  for (const [geo, v] of Object.entries(rates)) {
    if (suppressed.has(geo)) continue;
    if (v.White > 0 && v.Black != null) rriOf[geo] = v.Black / v.White;
  }

  // Equirectangular projection with latitude correction, fitted to the data.
  let lonMin = Infinity, lonMax = -Infinity, latMin = Infinity, latMax = -Infinity;
  for (const force of boundaries) {
    for (const ring of force.rings) {
      for (const [lon, lat] of ring) {
        if (lon < lonMin) lonMin = lon;
        if (lon > lonMax) lonMax = lon;
        if (lat < latMin) latMin = lat;
        if (lat > latMax) latMax = lat;
      }
    }
  }
  const kLat = Math.cos(((latMin + latMax) / 2) * Math.PI / 180);
  const mapH = 500;
  const scale = mapH / (latMax - latMin);
  const mapW = (lonMax - lonMin) * kLat * scale;
  const px = (lon) => ((lon - lonMin) * kLat * scale).toFixed(1);
  const py = (lat) => ((latMax - lat) * scale).toFixed(1);

  let paths = "";
  for (const force of boundaries) {
    const rri = rriOf[force.geo_id];
    const isSuppressed = suppressed.has(force.geo_id);
    const fill = rri == null
      ? (isSuppressed ? "url(#choro-hatch)" : "#f4f4f2")
      : choroplethColour(rri);
    const d = force.rings
      .map((ring) =>
        "M" + ring.map(([lon, lat]) => `${px(lon)},${py(lat)}`).join("L") + "Z")
      .join("");
    const label = isSuppressed
      ? `${force.geo_name}: search count below 6, suppressed for disclosure control`
      : rri == null
        ? `${force.geo_name}: no rate available`
        : `${force.geo_name}: RRI ${rri.toFixed(2)}`;
    paths +=
      `<path d="${d}" fill="${fill}" stroke="#ffffff" stroke-width="0.6">` +
      `<title>${label}</title></path>`;
  }

  // Legend: a horizontal ramp with ticks at 1, 2 and 3+.
  const legendStops = Array.from({ length: 24 }, (_, i) => {
    const t = i / 23;
    const x = (i * 5).toFixed(1);
    return `<rect x="${x}" y="0" width="5.2" height="10" ` +
      `fill="${choroplethColour(CHORO_MIN + t * (CHORO_MAX - CHORO_MIN))}"/>`;
  }).join("");
  const legend =
    `<g transform="translate(6,20)" font-size="10" fill="#5f5e5a">` +
    `<text x="0" y="-7" font-size="10.5">RRI, Black children, stop and search</text>` +
    legendStops +
    `<text x="0" y="22">1.0</text>` +
    `<text x="60" y="22" text-anchor="middle">2.0</text>` +
    `<text x="120" y="22" text-anchor="end">3.0+</text>` +
    `<rect x="150" y="0" width="14" height="10" fill="url(#choro-hatch)" stroke="#d8d6cf" stroke-width="0.5"/>` +
    `<text x="169" y="8.5">suppressed, count below 6</text>` +
    `</g>`;

  const svg =
    `<svg viewBox="0 0 ${Math.ceil(mapW + 12)} ${mapH + 56}" width="100%" ` +
    `style="max-width:430px;font-family:${UI_FONT}" role="img" ` +
    `aria-labelledby="choro-title-svg">` +
    `<title id="choro-title-svg">Map of England and Wales police force areas ` +
    `shaded by the stop-and-search Relative Rate Index for Black children</title>` +
    `<defs><pattern id="choro-hatch" width="5" height="5" patternUnits="userSpaceOnUse" ` +
    `patternTransform="rotate(45)"><rect width="5" height="5" fill="#f1f0ec"/>` +
    `<line x1="0" y1="0" x2="0" y2="5" stroke="#c9c7bf" stroke-width="1.4"/></pattern></defs>` +
    legend +
    `<g transform="translate(6,52)">${paths}</g>` +
    `</svg>`;

  const values = Object.values(rriOf).sort((a, b) => a - b);
  const median = values[Math.floor(values.length / 2)];
  return { svg, forces: values.length, suppressed: suppressed.size,
           median: median.toFixed(2),
           min: values[0].toFixed(2), max: values[values.length - 1].toFixed(2) };
}


// --------------------------------------------------------------------------
// Target tracker charts, from target_tracker.json
//
// Three hand-built inline SVGs in the cascade's design language: the
// rolling-average remand stock against the baseline and the 25% target, the
// whole-custody ethnic composition companion, and median remand nights by
// binary ethnicity.
// --------------------------------------------------------------------------
const TRACKER_INK = "#1B3A5F";
const TRACKER_RAW = "#c3cdd8";
const TRACKER_TARGET = "#1D9E75";
const TRACKER_GREY = "#888780";

function monthIndex(months, month) {
  return months.indexOf(month);
}

export function renderTargetTracker() {
  const payload = load("target_tracker.json");
  const stock = payload.records.filter((r) => r.block === "stock_monthly");
  const meta = payload.meta.stock;
  const months = stock.map((r) => r.month);

  const W = 640, H = 250, PADL = 34;
  const x = (i) => PADL + (i / (months.length - 1)) * (W - PADL);
  const yMin = 100, yMax = 280;
  const y = (v) => H - ((v - yMin) / (yMax - yMin)) * H;

  const rawPath = stock
    .map((r, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(r.remand).toFixed(1)}`)
    .join("");
  const rollPts = stock.filter((r) => r.rolling_avg_12m != null);
  const rollPath = rollPts
    .map((r, i) => `${i ? "L" : "M"}${x(monthIndex(months, r.month)).toFixed(1)},` +
      `${y(r.rolling_avg_12m).toFixed(1)}`)
    .join("");

  // Year ticks every two years, plus gridlines at 100/150/200/250.
  let axis = "";
  for (const value of [100, 150, 200, 250]) {
    axis += `<line x1="${PADL}" y1="${y(value).toFixed(1)}" x2="${W}" ` +
      `y2="${y(value).toFixed(1)}" stroke="#F1EFE8" stroke-width="0.5"/>` +
      `<text x="${PADL - 6}" y="${y(value).toFixed(1)}" text-anchor="end" ` +
      `dominant-baseline="middle" font-size="10" fill="${TRACKER_GREY}">${value}</text>`;
  }
  for (let year = 2016; year <= 2026; year += 2) {
    const i = monthIndex(months, `${year}-01`);
    if (i < 0) continue;
    axis += `<text x="${x(i).toFixed(1)}" y="${H + 16}" text-anchor="middle" ` +
      `font-size="10" fill="${TRACKER_GREY}">${year}</text>`;
  }

  // Baseline and target lines.
  const guides =
    `<line x1="${PADL}" y1="${y(meta.baseline).toFixed(1)}" x2="${W}" ` +
    `y2="${y(meta.baseline).toFixed(1)}" stroke="${TRACKER_GREY}" ` +
    `stroke-width="1" stroke-dasharray="4 4"/>` +
    `<text x="${W}" y="${(y(meta.baseline) - 5).toFixed(1)}" text-anchor="end" ` +
    `font-size="10" fill="#5F5E5A">baseline ${meta.baseline.toFixed(0)}</text>` +
    `<line x1="${PADL}" y1="${y(meta.target).toFixed(1)}" x2="${W}" ` +
    `y2="${y(meta.target).toFixed(1)}" stroke="${TRACKER_TARGET}" ` +
    `stroke-width="1.2" stroke-dasharray="6 3"/>` +
    `<text x="${W}" y="${(y(meta.target) + 12).toFixed(1)}" text-anchor="end" ` +
    `font-size="10" fill="#0F6E56">25% target ${meta.target.toFixed(0)}</text>`;

  // Markers: February 2026 and the White Paper (18 May 2026).
  let markers = "";
  const feb = monthIndex(months, "2026-02");
  const may = monthIndex(months, "2026-05");
  for (const [i, label, dy] of [[feb, "Feb 2026: 149 on remand", -8],
                                [may, "White Paper, 18 May 2026", -30]]) {
    if (i < 0) continue;
    markers += `<line x1="${x(i).toFixed(1)}" y1="14" x2="${x(i).toFixed(1)}" ` +
      `y2="${H}" stroke="#D3D1C7" stroke-width="0.8"/>` +
      `<text x="${(x(i) - 4).toFixed(1)}" y="${H + dy}" text-anchor="end" ` +
      `font-size="9.5" fill="#5F5E5A">${label}</text>`;
  }

  const latestI = monthIndex(months, meta.latest_month);
  const latestDot =
    `<circle cx="${x(latestI).toFixed(1)}" ` +
    `cy="${y(meta.latest_rolling_avg).toFixed(1)}" r="3.5" fill="${TRACKER_INK}"/>`;

  const svg = `<svg viewBox="0 0 ${W + 8} ${H + 24}" width="100%" role="img" ` +
    `aria-labelledby="tracker-svg-title" style="font-family:${UI_FONT}">` +
    `<title id="tracker-svg-title">The youth estate remand population, ` +
    `12-month rolling average, against the March 2025 baseline and the 25% ` +
    `reduction target</title>` +
    axis + guides + markers +
    `<path d="${rawPath}" fill="none" stroke="${TRACKER_RAW}" stroke-width="1"/>` +
    `<path d="${rollPath}" fill="none" stroke="${TRACKER_INK}" stroke-width="2.4" ` +
    `stroke-linecap="round"/>` + latestDot +
    `</svg>`;

  const monthName = (ym) => new Date(`${ym}-01`).toLocaleString("en-GB",
    { month: "long", year: "numeric" });
  const change = meta.change_from_baseline_pct;
  const position =
    `As of ${monthName(meta.latest_month)}` +
    `${meta.latest_provisional ? " (provisional)" : ""}, the 12-month average ` +
    `remand population is ${Math.round(meta.latest_rolling_avg)}, ` +
    `${Math.abs(change).toFixed(1)}% ${change < 0 ? "below" : "above"} the ` +
    `March 2025 baseline.`;
  const trend = meta.pre_commitment_trend;
  const preCommitment =
    `The remand population was already falling before the White Paper: ` +
    `${trend < 0 ? "down" : "up"} ${Math.abs(trend).toFixed(1)}% between ` +
    `March 2025 and May 2026.`;

  return { svg, position, preCommitment };
}

export function renderCustodyEthnicityCompanion() {
  const payload = load("target_tracker.json");
  const rows = payload.records.filter(
    (r) => r.block === "whole_custody_ethnicity_monthly" &&
      (r.category === "black" || r.category === "mixed") &&
      r.month >= "2015-04");
  const months = [...new Set(rows.map((r) => r.month))].sort();

  const W = 640, H = 120, PADL = 34;
  const x = (i) => PADL + (i / (months.length - 1)) * (W - PADL);
  const y = (share) => H - (share / 0.3) * H;

  const line = (category, colour) => {
    const pts = months
      .map((m, i) => {
        const row = rows.find((r) => r.month === m && r.category === category);
        return row && row.share != null
          ? `${x(i).toFixed(1)},${y(row.share).toFixed(1)}` : null;
      })
      .filter(Boolean);
    return `<polyline points="${pts.join(" ")}" fill="none" stroke="${colour}" ` +
      `stroke-width="2"/>`;
  };

  let axis = "";
  for (const share of [0.1, 0.2, 0.3]) {
    axis += `<line x1="${PADL}" y1="${y(share).toFixed(1)}" x2="${W}" ` +
      `y2="${y(share).toFixed(1)}" stroke="#F1EFE8" stroke-width="0.5"/>` +
      `<text x="${PADL - 6}" y="${y(share).toFixed(1)}" text-anchor="end" ` +
      `dominant-baseline="middle" font-size="9.5" fill="${TRACKER_GREY}">` +
      `${Math.round(share * 100)}%</text>`;
  }
  for (let year = 2016; year <= 2026; year += 2) {
    const i = months.indexOf(`${year}-01`);
    if (i >= 0) axis += `<text x="${x(i).toFixed(1)}" y="${H + 14}" ` +
      `text-anchor="middle" font-size="9.5" fill="${TRACKER_GREY}">${year}</text>`;
  }

  const svg = `<svg viewBox="0 0 ${W + 8} ${H + 20}" width="100%" role="img" ` +
    `aria-labelledby="companion-svg-title" style="font-family:${UI_FONT}">` +
    `<title id="companion-svg-title">Black and Mixed Heritage shares of the ` +
    `whole custody population, monthly</title>` +
    axis + line("black", "#534AB7") + line("mixed", "#D85A30") +
    `</svg>`;
  return svg;
}

export function renderRemandDuration() {
  const payload = load("target_tracker.json");
  const rows = payload.records.filter((r) => r.block === "duration_median_nights");
  const years = [...new Set(rows.map((r) => r.year_ending_march))].sort();

  const W = 560, rowH = 30, PADL = 96, PADR = 40;
  const H = 26 + years.length * rowH;
  const xMax = 80;
  const x = (v) => PADL + (v / xMax) * (W - PADL - PADR);

  let body = "";
  for (const value of [0, 20, 40, 60, 80]) {
    body += `<line x1="${x(value).toFixed(1)}" y1="18" x2="${x(value).toFixed(1)}" ` +
      `y2="${H - 8}" stroke="#F1EFE8" stroke-width="0.5"/>` +
      `<text x="${x(value).toFixed(1)}" y="12" text-anchor="middle" ` +
      `font-size="9.5" fill="${TRACKER_GREY}">${value}</text>`;
  }
  years.forEach((year, i) => {
    const cy = 30 + i * rowH;
    const white = rows.find((r) => r.year_ending_march === year &&
      r.ethnicity_group === "white");
    const minority = rows.find((r) => r.year_ending_march === year &&
      r.ethnicity_group === "ethnic_minority");
    const label = `${year - 1}-${String(year).slice(2)}` +
      (minority.provisional ? "*" : "");
    body += `<text x="0" y="${cy}" dominant-baseline="middle" font-size="11" ` +
      `fill="#444441">YE Mar ${label}</text>`;
    if (white.median_nights != null && minority.median_nights != null) {
      body += `<line x1="${x(white.median_nights).toFixed(1)}" y1="${cy}" ` +
        `x2="${x(minority.median_nights).toFixed(1)}" y2="${cy}" ` +
        `stroke="#D3D1C7" stroke-width="2"/>` +
        `<circle cx="${x(white.median_nights).toFixed(1)}" cy="${cy}" r="4.5" ` +
        `fill="#9aa7b4"/>` +
        `<circle cx="${x(minority.median_nights).toFixed(1)}" cy="${cy}" r="4.5" ` +
        `fill="${TRACKER_INK}"/>` +
        `<text x="${(x(minority.median_nights) + 9).toFixed(1)}" y="${cy}" ` +
        `dominant-baseline="middle" font-size="10.5" font-weight="600" ` +
        `fill="${TRACKER_INK}">${minority.median_nights}</text>` +
        `<text x="${(x(white.median_nights) - 9).toFixed(1)}" y="${cy}" ` +
        `dominant-baseline="middle" font-size="10.5" text-anchor="end" ` +
        `fill="#5F5E5A">${white.median_nights}</text>`;
    }
  });

  return `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" ` +
    `aria-labelledby="duration-svg-title" style="font-family:${UI_FONT}">` +
    `<title id="duration-svg-title">Median remand nights by ethnicity group ` +
    `and year: ethnic minority groups against White</title>` + body + `</svg>`;
}
