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

// Restrained editorial palette: muted, distinct, not a government dashboard.
const ETHNICITY_COLOUR = {
  Black: "#b3242b",
  Asian: "#2a6f4e",
  Mixed: "#9a6a2f",
  Other: "#5a4e7c",
};
const CASCADE_GROUPS = ["Black", "Asian", "Mixed", "Other"];
const STAGES = ["Stop and search", "Arrest", "Remand", "Custodial sentence"];

const FONT = "'Source Serif 4', Georgia, serif";


// --------------------------------------------------------------------------
// Chart A: the road-to-remand cascade
// --------------------------------------------------------------------------
export function renderCascade() {
  const rri = load("rri.json").records;

  const stageOf = {
    stop_search: "Stop and search",
    arrest: "Arrest",
    remand: "Remand",
    custodial_sentence: "Custodial sentence",
  };
  const rows = [];
  for (const record of rri) {
    if (record.provenance !== "prism_r_derived") continue;
    const stage = stageOf[record.decision_point];
    if (!stage) continue;
    // Custodial sentencing uses the three-year pooled estimate.
    if (record.decision_point === "custodial_sentence" && !record.pooled) continue;
    if (!CASCADE_GROUPS.includes(record.ethnicity)) continue;
    rows.push({ stage, ethnicity: record.ethnicity, rri: record.rri });
  }
  const maxRri = Math.max(...rows.map((r) => r.rri));

  return render({
    width: 680,
    height: 440,
    marginTop: 28,
    marginLeft: 58,
    marginRight: 96,
    marginBottom: 64,
    style: { fontFamily: FONT, fontSize: "13px", background: "transparent" },
    x: {
      domain: STAGES,
      label: null,
      tickSize: 0,
    },
    y: {
      domain: [0, Math.ceil(maxRri * 10) / 10 + 0.2],
      label: "Relative Rate Index",
      grid: true,
      ticks: 6,
    },
    color: { domain: CASCADE_GROUPS, range: CASCADE_GROUPS.map((g) => ETHNICITY_COLOUR[g]) },
    marks: [
      Plot.ruleY([1], { stroke: "#9a9a9a", strokeDasharray: "5 4" }),
      Plot.text([{ stage: "Stop and search", rri: 1 }], {
        x: "stage",
        y: "rri",
        text: ["White baseline, 1.0"],
        dy: 14,
        dx: 2,
        textAnchor: "start",
        fill: "#6a6a6a",
        fontSize: 11,
      }),
      Plot.line(rows, {
        x: "stage",
        y: "rri",
        z: "ethnicity",
        stroke: "ethnicity",
        strokeWidth: 2.4,
      }),
      Plot.dot(rows, {
        x: "stage",
        y: "rri",
        z: "ethnicity",
        fill: "ethnicity",
        r: 4.5,
      }),
      Plot.text(rows, {
        x: "stage",
        y: "rri",
        text: (d) => d.rri.toFixed(2),
        fill: "ethnicity",
        dy: -11,
        fontSize: 11.5,
        fontWeight: 600,
      }),
      // Ethnicity name at the end of each line, in the right margin.
      Plot.text(rows.filter((r) => r.stage === "Custodial sentence"), {
        x: "stage",
        y: "rri",
        text: "ethnicity",
        fill: "ethnicity",
        dx: 14,
        textAnchor: "start",
        fontSize: 12,
        fontWeight: 600,
      }),
    ],
  });
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
