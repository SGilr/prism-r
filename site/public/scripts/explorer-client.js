/**
 * The geographic explorer, running in the browser.
 *
 * The page ships with the geography index inlined, so the search list and
 * the framing are usable before any fetch completes. Boundary and indicator
 * payloads are fetched per level, on demand, and cached: a visitor who never
 * leaves the default view downloads one boundary layer and one data file.
 *
 * The map is one route to the data, not the only one. Every geography is
 * reachable from the search list, each geography is a focusable button, and
 * the panel is the same whichever route opened it. Colour never carries
 * meaning alone: the value is in the tooltip, the panel and the list.
 */

import { toCsv, downloadCsv, exportValue, exportStatus, slug }
  from "/scripts/csv.mjs";

const SUPPRESSED_LABEL = "<6, suppressed for disclosure control";

// The summary panel shows every group for every indicator, in the order the
// Lambeth worked example uses, so that page can be reproduced for any area.
const PANEL_GROUPS = [
  ["overall", "All children"], ["White", "White"], ["Black", "Black"],
  ["Asian", "Asian"], ["Mixed", "Mixed"], ["Other", "Other"],
];
// Areas with a written worked example on the site.
const WORKED_EXAMPLES = { E09000022: "/example-lambeth" };
const RATE_HIDDEN_LABEL = "rate not shown, population too small";

// Sequential ramp, light to the wordmark slate. Deliberately not a red-green
// diverging scale: these indicators have no neutral midpoint, and a diverging
// scale would imply one.
const RAMP = ["#eff1f3", "#d3dce4", "#aebecd", "#8399b0", "#587690", "#1b3a5f"];

export function initExplorer(root, index) {
  const state = {
    indicator: "suspension_rate",
    ethnicity: "overall",
    year: null,
    selected: null,
    level: null,
  };
  const cache = { boundaries: {}, records: {} };
  const catalogue = index.meta.indicators;
  const geographies = index.geographies;

  const el = (id) => root.querySelector(`#${id}`);
  const byId = new Map();
  for (const geography of geographies) {
    byId.set(`${geography.level}|${geography.geo_id}`, geography);
  }

  // ---------------------------------------------------------------- data
  async function load(kind, level) {
    const store = kind === "boundaries" ? cache.boundaries : cache.records;
    if (store[level]) return store[level];
    const url = kind === "boundaries"
      ? `/data/boundaries/${level}.topo.json`
      : `/data/explorer/${level}.json`;
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${url}: ${response.status}`);
    const payload = await response.json();
    store[level] = kind === "boundaries" ? payload : payload.records;
    return store[level];
  }

  function yearsFor(indicator, records) {
    return [...new Set(records.filter((r) => r.indicator === indicator)
      .map((r) => r.year))].sort((a, b) => b - a);
  }

  function cellsFor(records, indicator, year, ethnicity) {
    // A single-vintage indicator holds one figure per geography, published
    // on different dates in each nation: English IDACI 2025 and Welsh WIMD
    // 2019 are parallel scales, not a time series, so filtering by year
    // would blank a nation rather than move through time.
    const singleVintage = catalogue[indicator].single_vintage;
    const cells = new Map();
    for (const record of records) {
      if (record.indicator !== indicator) continue;
      if (!singleVintage && record.year !== year) continue;
      if ((record.ethnicity || "overall") !== ethnicity) continue;
      cells.set(record.geo_id, record);
    }
    return cells;
  }

  // ------------------------------------------------------------ rendering
  function formatValue(record, indicator) {
    if (!record) return { text: "no data published", muted: true };
    if (record.suppressed || record.disclosure_status === "source_suppressed") {
      return { text: SUPPRESSED_LABEL, muted: true };
    }
    if (record.disclosure_status === "rate_hidden") {
      return { text: RATE_HIDDEN_LABEL, muted: true };
    }
    if (record.value == null) return { text: "no data published", muted: true };
    const spec = catalogue[indicator];
    const value = spec.value_type === "count"
      ? record.value.toLocaleString("en-GB")
      : record.value.toFixed(spec.value_field === "rate_per_1000" ? 1 : 2);
    return { text: `${value} ${spec.unit}`, muted: false, raw: record.value };
  }

  function colourFor(value, breaks) {
    if (value == null) return "#f6f5f0";
    let index = 0;
    while (index < breaks.length && value > breaks[index]) index += 1;
    return RAMP[Math.min(index, RAMP.length - 1)];
  }

  function quantileBreaks(values) {
    const sorted = [...values].sort((a, b) => a - b);
    if (!sorted.length) return [];
    return [0.17, 0.33, 0.5, 0.67, 0.83]
      .map((q) => sorted[Math.floor(q * (sorted.length - 1))]);
  }

  // Decode TopoJSON to SVG paths. Kept local: the whole decoder is smaller
  // than a mapping library and needs no third-party code at runtime.
  function decode(topology) {
    const { scale: [sx, sy], translate: [ox, oy] } = topology.transform;
    const arcs = topology.arcs.map((arc) => {
      let x = 0, y = 0;
      return arc.map(([dx, dy]) => {
        x += dx; y += dy;
        return [x * sx + ox, y * sy + oy];
      });
    });
    const ring = (indexes) => {
      const points = [];
      for (const index of indexes) {
        const reversed = index < 0;
        const arc = arcs[reversed ? ~index : index];
        const segment = reversed ? [...arc].reverse() : arc;
        points.push(...(points.length ? segment.slice(1) : segment));
      }
      return points;
    };
    return topology.objects.data.geometries.map((geometry) => {
      const polygons = geometry.type === "MultiPolygon"
        ? geometry.arcs : [geometry.arcs];
      const rings = polygons.flatMap((polygon) => polygon.map(ring));
      return { properties: geometry.properties, rings };
    });
  }

  function project(features) {
    let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
    for (const feature of features) {
      for (const ring of feature.rings) {
        for (const [x, y] of ring) {
          if (x < minX) minX = x;
          if (x > maxX) maxX = x;
          if (y < minY) minY = y;
          if (y > maxY) maxY = y;
        }
      }
    }
    const width = 560;
    const k = Math.cos(((minY + maxY) / 2) * Math.PI / 180);
    const scale = width / ((maxX - minX) * k);
    const height = (maxY - minY) * scale;
    return {
      width, height,
      path: (rings) => rings.map((ring) =>
        "M" + ring.map(([x, y]) =>
          `${((x - minX) * k * scale).toFixed(1)},${((maxY - y) * scale).toFixed(1)}`
        ).join("L") + "Z").join(""),
    };
  }

  async function render() {
    const spec = catalogue[state.indicator];
    const level = spec.level;
    el("explorer-status").textContent = "Loading…";

    const [topology, records] = await Promise.all([
      load("boundaries", level), load("records", level),
    ]);
    const years = yearsFor(state.indicator, records);
    if (!years.includes(state.year)) state.year = years[0];
    state.level = level;

    // Year and ethnicity controls follow the indicator.
    const yearSelect = el("explorer-year");
    if (spec.single_vintage) {
      yearSelect.innerHTML =
        `<option>latest published in each nation</option>`;
      yearSelect.disabled = true;
    } else {
      yearSelect.innerHTML = years.map((year) =>
        `<option value="${year}"${year === state.year ? " selected" : ""}>${
          yearLabel(year, records)}</option>`).join("");
      yearSelect.disabled = years.length < 2;
    }

    const cells = cellsFor(records, state.indicator, state.year, state.ethnicity);
    const values = [...cells.values()]
      .filter((r) => !r.suppressed && r.value != null).map((r) => r.value);
    const breaks = quantileBreaks(values);

    const features = decode(topology);
    const projection = project(features);
    const paths = features.map((feature) => {
      const geoId = feature.properties.geo_id;
      const record = cells.get(geoId);
      const formatted = formatValue(record, state.indicator);
      const fill = record && !formatted.muted
        ? colourFor(record.value, breaks) : "url(#no-data)";
      const selected = state.selected === geoId;
      return `<path d="${projection.path(feature.rings)}" fill="${fill}" ` +
        `stroke="${selected ? "#161512" : "#ffffff"}" ` +
        `stroke-width="${selected ? 1.6 : 0.4}" tabindex="0" role="button" ` +
        `data-geo="${geoId}" aria-label="${escape(feature.properties.geo_name)}: ${
          escape(formatted.text)}"><title>${escape(feature.properties.geo_name)}: ${
          escape(formatted.text)}</title></path>`;
    }).join("");

    el("explorer-map").innerHTML =
      `<svg viewBox="0 0 ${projection.width} ${Math.ceil(projection.height)}" ` +
      `width="100%" role="group" aria-label="Map of ${spec.label} by ${
        index.meta.levels[level].label.toLowerCase()}">` +
      `<defs><pattern id="no-data" width="6" height="6" ` +
      `patternUnits="userSpaceOnUse" patternTransform="rotate(45)">` +
      `<rect width="6" height="6" fill="#f6f5f0"/>` +
      `<line x1="0" y1="0" x2="0" y2="6" stroke="#dcdad2" stroke-width="1.6"/>` +
      `</pattern></defs>${paths}</svg>`;

    el("explorer-level-note").textContent = spec.level_note;
    el("explorer-legend").innerHTML = legend(breaks, spec);
    const areaCount = geographies.filter((g) => g.level === level).length;
    const withFigure = values.length;
    const suppressedCount = [...cells.values()].filter(
      (r) => r.suppressed || r.disclosure_status === "source_suppressed").length;
    const absent = areaCount - withFigure - suppressedCount;
    const parts = [`${areaCount} ${index.meta.levels[level].plural}`,
                   `${withFigure} with a published figure`];
    if (suppressedCount) {
      parts.push(`${suppressedCount} suppressed for disclosure control`);
    }
    if (absent > 0) {
      parts.push(`${absent} where this indicator is not published for this period`);
    }
    el("explorer-status").textContent = `${parts.join(", ")}.`;
    renderList(cells);
    if (state.selected) renderPanel(state.selected);
    root.querySelectorAll("#explorer-map path").forEach((path) => {
      path.addEventListener("click", () => select(path.dataset.geo));
      path.addEventListener("keydown", (event) => {
        if (event.key === "Enter" || event.key === " ") {
          event.preventDefault();
          select(path.dataset.geo);
        }
      });
    });
  }

  function yearLabel(year, records) {
    const record = records.find((r) => r.year === year &&
      r.indicator === state.indicator);
    const source = record ? index.sources[record.source_key] : null;
    return source ? source.reference_period : String(year);
  }

  function legend(breaks, spec) {
    if (!breaks.length) return "";
    const swatches = RAMP.map((colour, i) => {
      const from = i === 0 ? "lowest" : breaks[i - 1].toFixed(
        spec.value_type === "count" ? 0 : 2);
      return `<span class="key"><span class="sw" style="background:${colour}"></span>` +
        `${i === 0 ? "lowest" : from}</span>`;
    }).join("");
    return swatches +
      `<span class="key"><span class="sw sw-none"></span>no published figure</span>`;
  }

  function renderList(cells) {
    const query = el("explorer-search").value.trim().toLowerCase();
    const rows = geographies
      .filter((g) => g.level === state.level)
      .filter((g) => !query || g.geo_name.toLowerCase().includes(query))
      .sort((a, b) => a.geo_name.localeCompare(b.geo_name))
      .map((g) => {
        const formatted = formatValue(cells.get(g.geo_id), state.indicator);
        return `<li><button type="button" data-geo="${g.geo_id}"${
          state.selected === g.geo_id ? ' aria-current="true"' : ""}>` +
          `<span class="name">${escape(g.geo_name)}</span>` +
          `<span class="value${formatted.muted ? " muted" : ""}">${
            escape(formatted.text)}</span></button></li>`;
      });
    el("explorer-list").innerHTML = rows.join("") ||
      `<li class="empty">No area matches that search.</li>`;
    el("explorer-list-count").textContent =
      `${rows.length} areas${query ? " matching" : ""}`;
    root.querySelectorAll("#explorer-list button").forEach((button) => {
      button.addEventListener("click", () => select(button.dataset.geo));
    });
  }

  function select(geoId) {
    state.selected = geoId;
    renderPanel(geoId);
    // A selected area is a linkable view: /explore?area=E09000022 reopens it.
    history.replaceState(null, "", `?area=${encodeURIComponent(geoId)}`);
    root.querySelectorAll("#explorer-map path").forEach((path) => {
      const isSelected = path.dataset.geo === geoId;
      path.setAttribute("stroke", isSelected ? "#161512" : "#ffffff");
      path.setAttribute("stroke-width", isSelected ? "1.6" : "0.4");
    });
    root.querySelectorAll("#explorer-list button").forEach((button) => {
      if (button.dataset.geo === geoId) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    });
  }

  async function renderPanel(geoId) {
    const geography = byId.get(`${state.level}|${geoId}`) ||
      geographies.find((g) => g.geo_id === geoId);
    if (!geography) return;
    const panel = el("explorer-panel");

    // Every indicator for this place, each at its own level, and within each
    // indicator every ethnic group against the national figure. The map's
    // ethnicity filter does not narrow this: the panel is the area read
    // together, which is what the Lambeth worked example shows. An indicator
    // published for a different geography is named as unavailable here, with
    // the geography that does hold it, rather than borrowing its value.
    const blocks = [];
    for (const [indicator, spec] of Object.entries(catalogue)) {
      if (indicator === "child_population") continue;  // stated in the header
      // A unitary, metropolitan, London or Welsh authority is both a
      // district and an upper-tier authority, so an indicator published at
      // either level is genuinely this authority's own figure. Only a
      // geography that does not exist at the indicator's level is told the
      // indicator is published elsewhere.
      const servedLevel = state.level === "rgn" && spec.level === "utla"
        ? "rgn"
        : (byId.has(`${spec.level}|${geoId}`) ? spec.level : null);
      const head =
        `<dt>${escape(spec.label)}<span class="unit">${escape(spec.unit)}</span>` +
        `<a class="methods-link" href="/methods#${spec.methods_anchor}" ` +
        `title="How this indicator is built">methods</a></dt>`;
      if (!servedLevel) {
        // Never borrow the parent's figure as if it were local, but make it
        // one click away: the Lambeth worked example shows the Met's stop
        // and search figures labelled as the force's, and this is how the
        // explorer reproduces that.
        const holder = { pfa: geography.parent_force, utla: geography.parent_utla }[spec.level];
        const open = holder
          ? ` <a class="open-holder" href="?area=${encodeURIComponent(holder)}">open it</a>`
          : "";
        blocks.push(`<div class="panel-row">${head}<dd class="muted">${
          escape(unavailableNote(indicator, spec, geography))}${open}</dd></div>`);
        continue;
      }
      const records = await load("records", servedLevel);
      const year = yearsFor(indicator, records)[0];
      const byGroup = PANEL_GROUPS.map(([key, label]) => [
        label, cellsFor(records, indicator, year, key).get(geoId) || null]);
      const present = byGroup.filter(([, r]) => r);
      if (!present.length) {
        blocks.push(`<div class="panel-row">${head}<dd class="muted">no data published</dd></div>`);
        continue;
      }
      const first = present[0][1];
      const scope = first.national_scope || spec.national_scope;
      const source = index.sources[first.source_key];
      const fmt = (r) => formatValue(r, indicator);
      const nat = (r) => r && r.national_value != null
        ? (spec.value_type === "count"
            ? r.national_value.toLocaleString("en-GB")
            : r.national_value.toFixed(spec.value_field === "rate_per_1000" ? 1 : 2))
        : "";
      const rows = byGroup
        .filter(([, r]) => r || spec.single_vintage === false)
        .map(([label, r]) => {
          const f = fmt(r);
          const cell = f.muted ? `<td class="muted">${escape(f.text)}</td>`
                               : `<td>${escape(f.text.replace(` ${spec.unit}`, ""))}</td>`;
          return `<tr><th scope="row">${escape(label)}</th>${cell}` +
                 `<td class="national">${escape(nat(r))}</td></tr>`;
        }).join("");
      blocks.push(
        `<div class="panel-row">${head}<dd>` +
        `<table class="groups"><thead><tr><th scope="col"></th>` +
        `<th scope="col">${escape(geography.geo_name)}</th>` +
        `<th scope="col" class="national">${escape(scope)}</th></tr></thead>` +
        `<tbody>${rows}</tbody></table>` +
        (source ? `<span class="prov">${escape(source.reference_period)}. ${
          escape(source.source)}</span>` : "") +
        `</dd></div>`);
    }

    const population = geography.population_by_ethnicity || {};
    const populationTotal = Object.values(population).reduce((a, b) => a + b, 0);
    const parents = [];
    if (geography.parent_yot_name) {
      parents.push(`Youth justice service: ${escape(geography.parent_yot_name)}`);
    }
    if (geography.parent_force_name) {
      parents.push(`Police force: ${escape(geography.parent_force_name)}`);
    }
    if (geography.imd_decile_in_nation) {
      parents.push(`Child income deprivation decile within ${
        escape(geography.nation || "its nation")}: ${
        geography.imd_decile_in_nation} of 10`);
    }
    const example = WORKED_EXAMPLES[geoId]
      ? `<p class="panel-example">This authority has a written worked example: ` +
        `<a href="${WORKED_EXAMPLES[geoId]}">PRISM-R in ${escape(geography.geo_name)}</a>.</p>`
      : "";

    panel.innerHTML =
      `<h3>${escape(geography.geo_name)}</h3>` +
      `<p class="panel-level">${escape(index.meta.levels[geography.level].label)}` +
      (geography.nation === "Wales"
        ? `. Welsh deprivation is measured on the Welsh index (WIMD); it is a `
          + `separate scale from the English IDACI and the two are not comparable.`
        : "") + `</p>` +
      (parents.length ? `<p class="panel-parents">${parents.join(". ")}.</p>` : "") +
      (populationTotal ? `<p class="panel-parents">Child population aged 10 to 17: ${
        populationTotal.toLocaleString("en-GB")}.</p>` : "") +
      example +
      `<dl>${blocks.join("")}</dl>` +
      `<p class="panel-actions"><button type="button" id="explorer-export-panel">` +
      `Download this summary (CSV)</button></p>` +
      `<p class="panel-foot">Remand itself is not shown here: the Youth ` +
      `Justice Board does not publish it below England and Wales level. ` +
      `<a href="/national">See the national cascade</a>.</p>`;
    panel.hidden = false;
    panel.querySelector("#explorer-export-panel")
      .addEventListener("click", exportPanel);
  }

  function unavailableNote(indicator, spec, geography) {
    const holder = {
      pfa: geography.parent_force_name
        ? `the ${geography.parent_force_name} force area` : "police force area",
      utla: geography.parent_utla_name
        ? `${geography.parent_utla_name}` : "upper-tier authority",
      lad: "local authority district",
      rgn: "region",
    }[spec.level];
    return `not published at this level; published for ${holder}`;
  }

  function escape(value) {
    return String(value).replace(/&/g, "&amp;").replace(/</g, "&lt;")
      .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
  }

  // --------------------------------------------------------------- export
  /**
   * The current map view as CSV: one row per geography, carrying the same
   * provenance columns as the JSON. A suppressed cell exports blank with its
   * disclosure status, never a figure.
   */
  function exportView() {
    const spec = catalogue[state.indicator];
    const level = spec.level === "utla" && state.level === "rgn"
      ? "rgn" : state.level;
    const records = cache.records[level] || [];
    const years = yearsFor(state.indicator, records);
    const cells = cellsFor(records, state.indicator,
                           state.year || years[0], state.ethnicity);
    const columns = [
      { key: "geo_id", label: "geo_id" },
      { key: "geo_name", label: "geo_name" },
      { key: "geo_level", label: "geo_level" },
      { key: "indicator", label: "indicator" },
      { key: "indicator_label", label: "indicator_label" },
      { key: "year", label: "year" },
      { key: "ethnicity", label: "ethnicity" },
      { key: "value", label: "value" },
      { key: "unit", label: "unit" },
      { key: "numerator", label: "numerator" },
      { key: "denominator", label: "denominator" },
      { key: "national_value", label: "national_value" },
      { key: "national_scope", label: "national_scope" },
      { key: "source", label: "source" },
      { key: "reference_period", label: "reference_period" },
      { key: "disclosure_status", label: "disclosure_status" },
    ];
    const rows = geographies
      .filter((g) => g.level === level)
      .sort((a, b) => a.geo_name.localeCompare(b.geo_name))
      .map((g) => {
        const record = cells.get(g.geo_id);
        const source = record ? index.sources[record.source_key] : null;
        return {
          geo_id: g.geo_id,
          geo_name: g.geo_name,
          geo_level: index.meta.levels[level].label,
          indicator: state.indicator,
          indicator_label: spec.label,
          year: record?.year ?? "",
          ethnicity: state.ethnicity,
          value: exportValue(record),
          unit: spec.unit,
          numerator: record?.numerator ?? "",
          denominator: record?.denominator ?? "",
          national_value: record?.national_value ?? "",
          national_scope: record?.national_scope || spec.national_scope,
          source: source?.source ?? "",
          reference_period: source?.reference_period ?? "",
          disclosure_status: record ? exportStatus(record) : "not published",
        };
      });
    downloadCsv(
      `prism-r-${slug(spec.label)}-${slug(state.ethnicity)}.csv`,
      toCsv(columns, rows, {
        title: `PRISM-R: ${spec.label}, ${state.ethnicity === "overall"
          ? "all children" : state.ethnicity}, by ${
          index.meta.levels[level].label.toLowerCase()}`,
        note: spec.level_note,
      }));
  }

  /** The selected area's summary panel as CSV, one row per indicator. */
  async function exportPanel() {
    const geoId = state.selected;
    if (!geoId) return;
    const geography = byId.get(`${state.level}|${geoId}`) ||
      geographies.find((g) => g.geo_id === geoId);
    const columns = [
      { key: "geo_id", label: "geo_id" },
      { key: "geo_name", label: "geo_name" },
      { key: "indicator", label: "indicator" },
      { key: "indicator_label", label: "indicator_label" },
      { key: "published_at_level", label: "published_at_level" },
      { key: "year", label: "year" },
      { key: "ethnicity", label: "ethnicity" },
      { key: "value", label: "value" },
      { key: "unit", label: "unit" },
      { key: "national_value", label: "national_value" },
      { key: "national_scope", label: "national_scope" },
      { key: "source", label: "source" },
      { key: "reference_period", label: "reference_period" },
      { key: "disclosure_status", label: "disclosure_status" },
    ];
    const rows = [];
    for (const [indicator, spec] of Object.entries(catalogue)) {
      const servedLevel = state.level === "rgn" && spec.level === "utla"
        ? "rgn"
        : (byId.has(`${spec.level}|${geoId}`) ? spec.level : null);
      if (!servedLevel) {
        // Names the geography that holds the figure when it is not this one,
        // so a reader of the CSV alone cannot mistake a gap for a zero.
        rows.push({
          geo_id: geoId, geo_name: geography.geo_name, indicator,
          indicator_label: spec.label,
          published_at_level: `not published at this level; published at ${
            index.meta.levels[spec.level].label.toLowerCase()} level`,
          year: "", ethnicity: "", value: "", unit: spec.unit,
          national_value: "", national_scope: spec.national_scope,
          source: "", reference_period: "",
          disclosure_status: "not published at this level",
        });
        continue;
      }
      const records = await load("records", servedLevel);
      const year = yearsFor(indicator, records)[0];
      for (const [key] of PANEL_GROUPS) {
        const record = cellsFor(records, indicator, year, key).get(geoId) || null;
        if (!record && spec.single_vintage) continue;  // one figure, no groups
        const source = record ? index.sources[record.source_key] : null;
        rows.push({
          geo_id: geoId,
          geo_name: geography.geo_name,
          indicator,
          indicator_label: spec.label,
          published_at_level: index.meta.levels[servedLevel].label,
          year: record?.year ?? "",
          ethnicity: key,
          value: exportValue(record),
          unit: spec.unit,
          national_value: record?.national_value ?? "",
          national_scope: record?.national_scope || spec.national_scope,
          source: source?.source ?? "",
          reference_period: source?.reference_period ?? "",
          disclosure_status: record ? exportStatus(record) : "not published",
        });
      }
    }
    downloadCsv(`prism-r-${slug(geography.geo_name)}-summary.csv`,
      toCsv(columns, rows, {
        title: `PRISM-R: ${geography.geo_name}, every available indicator by ethnic group`,
        note: "Remand is not included: the Youth Justice Board does not "
            + "publish it below England and Wales level.",
      }));
  }

  // ------------------------------------------------------------- controls
  el("explorer-indicator").addEventListener("change", (event) => {
    state.indicator = event.target.value;
    render();
  });
  el("explorer-ethnicity").addEventListener("change", (event) => {
    state.ethnicity = event.target.value;
    render();
  });
  el("explorer-year").addEventListener("change", (event) => {
    state.year = Number(event.target.value);
    render();
  });
  el("explorer-export").addEventListener("click", exportView);
  el("explorer-search").addEventListener("input", () => {
    const spec = catalogue[state.indicator];
    load("records", spec.level).then((records) => {
      const years = yearsFor(state.indicator, records);
      renderList(cellsFor(records, state.indicator,
        state.year || years[0], state.ethnicity));
    });
  });

  // Open straight onto an area when linked to one. If the area does not
  // exist at the default indicator's level, for example a shire district
  // linked while an upper-tier indicator is selected, switch to the first
  // indicator whose level does hold it.
  const wanted = new URLSearchParams(location.search).get("area");
  if (wanted && geographies.some((g) => g.geo_id === wanted)) {
    const current = catalogue[state.indicator].level;
    if (!byId.has(`${current}|${wanted}`)) {
      const fallback = Object.entries(catalogue).find(([, spec]) =>
        byId.has(`${spec.level}|${wanted}`));
      if (fallback) {
        state.indicator = fallback[0];
        el("explorer-indicator").value = fallback[0];
      }
    }
  }

  render().then(() => {
    if (wanted && byId.has(`${state.level}|${wanted}`)) {
      select(wanted);
      el("explorer-panel").scrollIntoView({ block: "start", behavior: "smooth" });
    }
  }).catch((error) => {
    el("explorer-status").textContent =
      "The map data could not be loaded. The figures remain available in the " +
      "downloads on the methods page.";
    console.error(error);
  });
}
