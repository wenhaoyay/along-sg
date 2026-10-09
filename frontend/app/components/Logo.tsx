/* The mark is the product's one idea: a straight trip with a small detour in
 * it, and the stop at the top of the bump. It replaced a lettermark "A" in a
 * green square, which said nothing about what the app does. */
export function LogoMark({ size = 34 }: { size?: number }) {
  return (
    <svg
      className="logo-mark"
      width={size}
      height={size}
      viewBox="0 0 34 34"
      aria-hidden="true"
      focusable="false"
    >
      <rect width="34" height="34" rx="10" className="logo-ground" />
      <path
        d="M6 22.5h6.2c1.6 0 2.5-.9 3-2.3l.9-2.6c.5-1.4 1.4-2.1 2.6-2.1s2.1.7 2.6 2.1l.9 2.6c.5 1.4 1.4 2.3 3 2.3H28"
        className="logo-route"
      />
      <circle cx="6" cy="22.5" r="2.4" className="logo-end" />
      <circle cx="28" cy="22.5" r="2.4" className="logo-end" />
      <circle cx="18.7" cy="11" r="3.2" className="logo-stop" />
    </svg>
  );
}
