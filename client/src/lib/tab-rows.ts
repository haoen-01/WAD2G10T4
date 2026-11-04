/**
 * How many rows the phone tab bar (`components/ui/MainNav.vue`) needs so every label is shown
 * whole at the text size the person chose. Labels are never shrunk to fit: at a large text size
 * on a narrow phone the bar takes a second row instead. Pure, so it is tested in `tab-rows.test.ts`.
 */

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
