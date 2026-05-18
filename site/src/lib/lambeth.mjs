/**
 * Build-time data and panels for the Lambeth worked example.
 *
 * Reads the processed pipeline JSON, computes the six panels for Lambeth
 * (ONS code E09000022), and renders each as a compact inline-SVG horizontal
 * bar chart. Suppressed cells are shown with the disclosure module's display
 * string, never a guess.
 */
import { readFileSync } from "node:fs";

const PROCESSED = new URL("../../../data/processed/", import.meta.url);
const load = (name) => JSON.parse(readFileSync(new URL(name, PROCESSED), "utf-8"));

const LAMBETH = "E09000022";
const MET = "pf-london";
const ORDER = ["White", "Black", "Asian", "Mixed", "Other"];
const COLOUR = {
  White: "#9aa7b4",
  Black: "#534AB7",
  Asian: "#1D9E75",
  Mixed: "#D85A30",
  Other: "#888780",
};
const SUPPRESSED_LABEL = "<6, suppressed for disclosure control";
const UI = "Inter, system-ui, sans-serif";


// --------------------------------------------------------------------------
// Inline-SVG bar charts
// --------------------------------------------------------------------------
function escapeText(value) {
  return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;");
}

/**
 * A single-series horizontal bar chart. items: {label, value, display,
 * suppressed}. A suppressed item shows the disclosure string, no bar.
 */
function barChart(items, { max }) {
  const width = 318;
  const rowH = 34;
  const labelW = 58;
  const barX = labelW + 6;
  const barMax = width - barX - 52;
  const height = 10 + items.length * rowH;
  let body = "";
  items.forEach((item, i) => {
    const cy = 10 + i * rowH + rowH / 2;
    body +=
      `<text x="0" y="${cy}" dominant-baseline="middle" font-size="12" ` +
      `fill="#444441">${escapeText(item.label)}</text>`;
    if (item.suppressed) {
      body +=
        `<text x="${barX}" y="${cy}" dominant-baseline="middle" font-size="10.5" ` +
        `font-style="italic" fill="#888780">${SUPPRESSED_LABEL}</text>`;
      return;
    }
    const w = max > 0 ? Math.max(1, (item.value / max) * barMax) : 1;
    body +=
      `<rect x="${barX}" y="${cy - 9}" width="${w.toFixed(1)}" height="18" ` +
      `rx="1.5" fill="${COLOUR[item.label] || "#888780"}"/>` +
      `<text x="${(barX + w + 6).toFixed(1)}" y="${cy}" dominant-baseline="middle" ` +
      `font-size="11.5" font-weight="600" fill="#1a1a1a">${escapeText(item.display)}</text>`;
  });
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" ` +
    `style="font-family:${UI}"><g>${body}</g></svg>`;
}

/**
 * A paired horizontal bar chart: a primary value (Lambeth) and a secondary
 * value (England and Wales) per row.
 */
function pairedBarChart(items, { max }) {
  const width = 318;
  const rowH = 46;
  const labelW = 58;
  const barX = labelW + 6;
  const barMax = width - barX - 52;
  const height = 12 + items.length * rowH;
  let body = "";
  items.forEach((item, i) => {
    const top = 12 + i * rowH;
    body +=
      `<text x="0" y="${top + 20}" dominant-baseline="middle" font-size="12" ` +
      `fill="#444441">${escapeText(item.label)}</text>`;
    const draw = (value, display, y, fill) => {
      const w = max > 0 ? Math.max(1, (value / max) * barMax) : 1;
      return (
        `<rect x="${barX}" y="${y}" width="${w.toFixed(1)}" height="13" rx="1.5" ` +
        `fill="${fill}"/>` +
        `<text x="${(barX + w + 6).toFixed(1)}" y="${y + 7}" ` +
        `dominant-baseline="middle" font-size="11" fill="#1a1a1a">${escapeText(display)}</text>`
      );
    };
    body += draw(item.primary, item.primaryDisplay, top + 3, COLOUR[item.label] || "#888780");
    body += draw(item.secondary, item.secondaryDisplay, top + 20, "#cdd5db");
  });
  return `<svg viewBox="0 0 ${width} ${height}" width="100%" role="img" ` +
    `style="font-family:${UI}"><g>${body}</g></svg>`;
}


// --------------------------------------------------------------------------
// Panels
// --------------------------------------------------------------------------
export function renderLambeth() {
  const populations = load("populations.json").records;
  const context = load("context_indicators.json").records;

  // --- Panel 1: child population 10-17 by ethnicity, Lambeth vs E&W --------
  const lambethPop = {};
  const nationalPop = {};
  for (const r of populations) {
    if (r.population == null || !ORDER.includes(r.ethnicity)) continue;
    nationalPop[r.ethnicity] = (nationalPop[r.ethnicity] || 0) + r.population;
    if (r.geo_id === LAMBETH) {
      lambethPop[r.ethnicity] = (lambethPop[r.ethnicity] || 0) + r.population;
    }
  }
  const lambethTotal = ORDER.reduce((s, e) => s + (lambethPop[e] || 0), 0);
  const nationalTotal = ORDER.reduce((s, e) => s + (nationalPop[e] || 0), 0);
  const popItems = ORDER.map((e) => ({
    label: e,
    primary: (lambethPop[e] / lambethTotal) * 100,
    secondary: (nationalPop[e] / nationalTotal) * 100,
    primaryDisplay: `${((lambethPop[e] / lambethTotal) * 100).toFixed(1)}%`,
    secondaryDisplay: `${((nationalPop[e] / nationalTotal) * 100).toFixed(1)}%`,
  }));

  // --- Context-indicator helpers ------------------------------------------
  const byEthnicity = (indicator, geo) => {
    const rows = {};
    for (const r of context) {
      if (r.indicator === indicator && r.geo_id === geo && r.breakdown === "by_ethnicity") {
        rows[r.ethnicity] = r;
      }
    }
    return rows;
  };

  // --- Panel 2: stop and search, Met Police, rate per 1,000 ---------------
  const ss = byEthnicity("stop_search_rate", MET);
  const ssItems = ORDER.map((e) => ({
    label: e,
    value: ss[e]?.rate_per_1000 ?? 0,
    display: ss[e]?.rate_per_1000 != null ? ss[e].rate_per_1000.toFixed(1) : "n/a",
    suppressed: ss[e]?.suppressed === true,
  }));

  // --- Panels 3 and 4: exclusions and suspensions, Lambeth, rate per 100 ---
  const rateItems = (indicator) => {
    const rows = byEthnicity(indicator, LAMBETH);
    return ORDER.map((e) => ({
      label: e,
      value: rows[e]?.rate_per_100 ?? 0,
      display: rows[e]?.rate_per_100 != null ? rows[e].rate_per_100.toFixed(2) : "n/a",
      suppressed: rows[e]?.suppressed === true,
    }));
  };
  const exclItems = rateItems("permanent_exclusion_rate");
  const suspItems = rateItems("suspension_rate");

  // --- Panel 5: looked-after children, Lambeth, counts --------------------
  const lac = byEthnicity("lac_count", LAMBETH);
  const lacItems = ORDER.map((e) => ({
    label: e,
    value: lac[e]?.value ?? 0,
    display: lac[e]?.value != null ? String(lac[e].value) : "",
    suppressed: lac[e]?.suppressed === true,
  }));

  // --- Panel 6: IDACI -----------------------------------------------------
  const englandImd = context.filter(
    (r) => r.indicator === "imd_score" && r.jurisdiction === "England",
  );
  const englandMean =
    englandImd.reduce((s, r) => s + r.value, 0) / englandImd.length;
  const lambethImd = englandImd.find((r) => r.geo_id === LAMBETH);

  return {
    population: barPanelPaired(popItems),
    stopSearch: barChart(ssItems, { max: Math.max(...ssItems.map((d) => d.value)) }),
    exclusions: barChart(exclItems, { max: Math.max(...exclItems.map((d) => d.value)) }),
    suspensions: barChart(suspItems, { max: Math.max(...suspItems.map((d) => d.value)) }),
    lookedAfter: barChart(lacItems, { max: Math.max(...lacItems.map((d) => d.value)) }),
    idaci: {
      score: lambethImd.value.toFixed(3),
      englandMean: englandMean.toFixed(3),
      rank: lambethImd.rank,
      rankMax: lambethImd.rank_max,
      percentile: Math.round((1 - (lambethImd.rank - 1) / lambethImd.rank_max) * 100),
    },
  };
}

// Panel 1 wrapper: the paired chart plus a compact legend.
function barPanelPaired(items) {
  const max = Math.max(...items.flatMap((d) => [d.primary, d.secondary]));
  return (
    `<div class="paired-legend">` +
    `<span><span class="sw" style="background:#534AB7"></span>Lambeth</span>` +
    `<span><span class="sw" style="background:#cdd5db"></span>England and Wales</span>` +
    `</div>` +
    pairedBarChart(items, { max })
  );
}
