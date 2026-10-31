/** The hidden address domain of the shared demo logins; Supabase password sign-in needs an email. */
const DEMO_LOGIN_DOMAIN = 'silverloop.demo';

/**
 * The email to sign in with: a value with no `@` is a demo username, so it gets the hidden domain;
 * anything else is a real email. Blank stays blank, so it never becomes a bare `@silverloop.demo`.
 */
export function signInEmail(typed: string): string {
  const value = typed.trim();
  if (!value || value.includes('@')) return value;
  return `${value}@${DEMO_LOGIN_DOMAIN}`;
}
