/**
 * CSV export, shared by the explorer and the build-time chart pages.
 *
 * Every export carries the same provenance columns as the JSON, so a
 * downloaded file can be cited without returning to the site: source,
 * reference period and disclosure status travel with each row. A suppressed
 * cell exports with an empty value and its disclosure status, never a figure
 * and never a zero standing in for one.
 *
 * The header block above the columns names the tool, the extract date and
 * the licence, because these files are meant to be read by people who did
 * not download them.
 */

export const PROVENANCE_COLUMNS = [
  "source", "reference_period", "disclosure_status",
];

const SUPPRESSED_STATUSES = new Set(["suppressed", "source_suppressed"]);

/** RFC 4180 quoting: only where needed, so the common case stays readable. */
function cell(value) {
  if (value == null) return "";
  const text = String(value);
  return /[",\r\n]/.test(text) ? `"${text.replace(/"/g, '""')}"` : text;
}

/**
 * Build a CSV document.
 *
 * columns: [{key, label}]. rows: plain objects keyed by column key.
 * meta: {title, note, extracted, licence, citation}. The comment block is
 * prefixed with # so a spreadsheet import can skip it and a reader cannot
 * miss it.
 */
export function toCsv(columns, rows, meta = {}) {
  const extracted = meta.extracted || new Date().toISOString().slice(0, 10);
  const preamble = [
    `# ${meta.title || "PRISM-R export"}`,
    "# PRISM-R, an open tool for analysis of remand disproportionality in",
    "# the youth justice system of England and Wales. Oxon Advisory.",
    `# https://prism-r.howpreventionworks.com`,
    `# Extracted: ${extracted}`,
    meta.note ? `# ${meta.note}` : null,
    "# Contains public sector information licensed under the Open Government",
    "# Licence v3.0. Source and reference period are given per row.",
    "# A blank value with a disclosure_status of suppressed or",
    "# source_suppressed is a cell withheld under disclosure control; it is",
    "# not a zero and must not be treated as one.",
  ].filter(Boolean);

  const lines = [
    ...preamble,
    columns.map((c) => cell(c.label || c.key)).join(","),
    ...rows.map((row) => columns.map((c) => cell(row[c.key])).join(",")),
  ];
  return lines.join("\r\n") + "\r\n";
}

/**
 * A value cell for export: blank when the figure is withheld, so no
 * suppressed number is ever written out, and no placeholder is mistaken for
 * a measurement.
 */
export function exportValue(record) {
  const status = record?.disclosure_status;
  if (record?.suppressed === true || SUPPRESSED_STATUSES.has(status)) return "";
  return record?.value ?? "";
}

/** The disclosure status to publish, defaulting to released. */
export function exportStatus(record) {
  if (record?.suppressed === true && !record?.disclosure_status) {
    return "suppressed";
  }
  return record?.disclosure_status || "released";
}

/** Trigger a download in the browser. Inert during a build. */
export function downloadCsv(filename, text) {
  if (typeof document === "undefined") return;
  const blob = new Blob([text], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  // Revoke on the next tick: Safari needs the URL alive through the click.
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

/** A filesystem-safe slug for a filename fragment. */
export function slug(text) {
  return String(text).toLowerCase().replace(/[^a-z0-9]+/g, "-")
    .replace(/^-|-$/g, "");
}
