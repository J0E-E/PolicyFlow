// The Guide's four button variants (Guide §5), lowercase. Shared by both
// `Button` (a real `<button>`) and `ButtonLink` (a react-router `<Link>`) so the
// two render identically. Kept JSX-free in its own module — a clean Vite
// fast-refresh boundary, mirroring the `api/` and `session/` splits.

export type ButtonVariant = "filled" | "tonal" | "outlined" | "text";

/** The class list for a button of the given variant: the shared `.button` base
 *  plus the per-variant `.button-<variant>` rule (see `styles/button.css`). */
export function buttonClassName(variant: ButtonVariant): string {
  return `button button-${variant}`;
}
