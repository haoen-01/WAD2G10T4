/**
 * How long a code has left, in words. Coarse while there is more than an hour ("Expires in 7
 * days", "Expires in 5 hours", rounded down), then m:ss or h:mm:ss in the last hour, where seconds
 * matter. A code that is over reads "Code expired".
 */
export function expiryLabel(seconds: number): string {
  const total = Math.floor(seconds);
  if (!Number.isFinite(total) || total <= 0) return 'Code expired';
  if (total >= 3600) {
    const hours = Math.floor(total / 3600);
    if (hours >= 48) return `Expires in ${Math.floor(hours / 24)} days`;
    return `Expires in ${hours} ${hours === 1 ? 'hour' : 'hours'}`;
  }
  const minutes = Math.floor(total / 60);
  return `Expires in ${minutes}:${String(total % 60).padStart(2, '0')}`;
}
