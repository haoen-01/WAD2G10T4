/**
 * How many rows the phone tab bar (`components/ui/MainNav.vue`) and the senior's section bar
 * (`views/SeniorView.vue`) need so every label is shown whole at the text size the person chose,
 * and where the tab bar's highlight pill sits. Labels are never shrunk to fit: at a large text size
 * on a narrow phone the bar takes a second row instead. Pure, so it is tested in `tab-rows.test.ts`.
 */

/**
 * Space (px) a label keeps clear of its tab's edges, both sides together: 6 px a side, so the
 * widest label never sits closer than 12 px to its neighbour before the bar takes a second row.
 */
export const LABEL_ROOM = 12;

/** The fewest rows (and tabs per row) that give the widest label, plus `room`, a tab of its own. */
export function tabRows(
  labelWidths: readonly number[],
  barWidth: number,
  room: number,
): { rows: number; perRow: number } {
  const count = labelWidths.length;
  if (count === 0 || barWidth <= 0) return { rows: 1, perRow: Math.max(1, count) };
  const widest = Math.max(...labelWidths) + room;
  for (let rows = 1; rows < count; rows += 1) {
    const perRow = Math.ceil(count / rows);
    if (widest <= barWidth / perRow) return { rows, perRow };
  }
  return { rows: count, perRow: 1 };
}

/**
 * Where (px from the bar's left edge) the highlight pill starts: centred on its tab, but never past
 * either end of the bar, even when the tab is narrower than the pill (the end tabs at a large text
 * size).
 */
export function pillLeft(tabX: number, tabWidth: number, pillWidth: number, barWidth: number) {
  const centred = tabX + (tabWidth - pillWidth) / 2;
  return Math.min(Math.max(centred, 0), Math.max(0, barWidth - pillWidth));
}

/** One of the senior's section tabs, measured (px): its icon, its word, and its count if any. */
export interface SectionTab {
  icon: number;
  label: number;
  /** The ready-to-claim count's width, or 0 when there is none. */
  extra: number;
}

/**
 * How the senior's section tabs show: the icon above the word, beside it, or (a narrow phone at
 * the largest text) the word alone.
 */
export type SectionTabLook = 'stacked' | 'beside' | 'words';

/**
 * The senior's section bar (`views/SeniorView.vue`): how many rows, and how each tab shows.
 *
 * On a phone (`phone`), one row has the icon above the word, the narrowest a tab can be, with the
 * count floating on the icon's corner. When that does not fit, the bar takes more rows, and to keep
 * them short puts the icon beside the word (count still on the icon) if that needs no more rows
 * than stacking; failing that, the word alone (count raised after it), if that needs no more
 * rows; failing that, stacked. Wide screens always have the icon beside the word and the count in line.
 * `gap` is the space between icon, word and count. Every input is measured from the parts, not
 * from the current layout, so the answer never depends on itself.
 */
export function sectionTabLayout(
  tabs: readonly SectionTab[],
  barWidth: number,
  gap: number,
  phone: boolean,
): { rows: number; perRow: number; look: SectionTabLook } {
  const inline = (tab: SectionTab) => (tab.extra ? gap + tab.extra : 0);
  const fit = (widths: number[]) => {
    const rows = tabRows(widths, barWidth, LABEL_ROOM);
    // `tabRows` gives every tab a row of its own when nothing fits; say whether this really does.
    return { ...rows, fits: Math.max(0, ...widths) + LABEL_ROOM <= barWidth / rows.perRow };
  };
  const pick = (rows: { rows: number; perRow: number }, look: SectionTabLook) => ({
    rows: rows.rows,
    perRow: rows.perRow,
    look,
  });
  if (!phone)
    return pick(fit(tabs.map((tab) => tab.icon + gap + tab.label + inline(tab))), 'beside');
  const stacked = fit(tabs.map((tab) => Math.max(tab.icon, tab.label)));
  if (stacked.rows === 1) return pick(stacked, 'stacked');
  const beside = fit(tabs.map((tab) => tab.icon + gap + tab.label));
  if (beside.fits && beside.rows <= stacked.rows) return pick(beside, 'beside');
  // Words alone: the count is raised just after the word, half a gap away.
  const words = fit(tabs.map((tab) => tab.label + (tab.extra ? gap / 2 + tab.extra : 0)));
  if (words.fits && words.rows <= stacked.rows) return pick(words, 'words');
  return pick(stacked, 'stacked');
}
