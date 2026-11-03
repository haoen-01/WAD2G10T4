/**
 * What a person's round avatar shows: their photo when there is one that loaded, otherwise their
 * initials. Pure and free of Vue, so `lib/avatar.test.ts` can run it under Node's type stripping.
 *
 * No photo comes from anywhere yet: the API has no photo field. When it gains one, the screens pass
 * that URL straight to `MemberAvatar`'s `photo` prop; nothing else changes.
 */

/** Up to two initials from the first two words of a name: "Mdm Lim" is "ML", "" is "?". */
export function initialsOf(name: string): string {
  return (
    name
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map((part) => part[0])
      .join('')
      .toUpperCase() || '?'
  );
}

/** The photo to draw, or `null` to draw initials: none given, a blank one, or one that failed. */
export function avatarPhoto(photo: string | null | undefined, failed: boolean): string | null {
  const url = photo?.trim();
  return url && !failed ? url : null;
}

/** The photo's alt text: the person's name, so a screen reader hears who it is. */
export function avatarAlt(name: string): string {
  const trimmed = name.trim();
  return trimmed ? `Photo of ${trimmed}` : 'Photo';
}
