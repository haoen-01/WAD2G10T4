/**
 * How many rows the phone tab bar (`components/ui/MainNav.vue`) needs so every label is shown
 * whole at the text size the person chose, and where its highlight pill sits. Labels are never
 * shrunk to fit: at a large text size on a narrow phone the bar takes a second row instead. Pure,
 * so it is tested in `tab-rows.test.ts`.
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
