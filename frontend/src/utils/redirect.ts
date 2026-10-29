/**
 * Redirect hardening for the login flow.
 *
 * `RequireAuth` stores `location.pathname + location.search` in the router
 * state so that a user lands on the page they originally requested. That value
 * is attacker-influenced in so far as it comes from the address bar, and React
 * Router resolves targets such as `//evil.example` or `/\evil.example` as a
 * protocol-relative URL (GHSA-wrjc-x8rr-h8h6, fixed in 7.18). Restricting the
 * value to a plain same-origin path removes the redirect primitive from this
 * application regardless of the router build in use.
 */
export function safeRedirect(target: string | null | undefined, fallback = "/dashboard"): string {
  if (!target) return fallback;
  if (!target.startsWith("/")) return fallback;
  // Protocol-relative (`//host`) and backslash (`/\host`) forms are resolved by
  // browsers as an absolute URL to another origin.
  if (target.startsWith("//") || target.startsWith("/\\")) return fallback;
  // Control characters can be used to smuggle extra header/URL components.
  if (containsControlCharacter(target)) return fallback;
  return target;
}

function containsControlCharacter(value: string): boolean {
  for (const character of value) {
    const code = character.codePointAt(0) ?? 0;
    if (code < 0x20 || code === 0x7f) return true;
  }
  return false;
}
