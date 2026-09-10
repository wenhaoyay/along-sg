export type ThemePreference = "system" | "light" | "dark";

export const THEME_STORAGE_KEY = "along-theme";

/** Applied to <html> before first paint, and again on every change.
 *
 * Kept as a plain string so the same logic can run from the blocking inline
 * script in the document head, where no module is loaded yet. */
export const THEME_BOOTSTRAP = `(function(){try{
var stored=localStorage.getItem("${THEME_STORAGE_KEY}");
var pref=stored==="light"||stored==="dark"?stored:"system";
var dark=pref==="dark"||(pref==="system"&&window.matchMedia("(prefers-color-scheme: dark)").matches);
document.documentElement.setAttribute("data-theme",dark?"dark":"light");
}catch(e){document.documentElement.setAttribute("data-theme","light");}})();`;

function read(): ThemePreference {
  try {
    const stored = localStorage.getItem(THEME_STORAGE_KEY);
    return stored === "light" || stored === "dark" ? stored : "system";
  } catch {
    // Private browsing and blocked site data both throw on access.
    return "system";
  }
}

export function resolveTheme(preference: ThemePreference): "light" | "dark" {
  if (preference !== "system") return preference;
  return typeof window !== "undefined" && window.matchMedia("(prefers-color-scheme: dark)").matches
    ? "dark"
    : "light";
}

/** The browser chrome is tinted by <meta name="theme-color">, which carries a
 * per-scheme media attribute. An explicit override has to retint it directly,
 * or the address bar stays on the system scheme while the page does not. */
export function applyTheme(preference: ThemePreference): "light" | "dark" {
  const theme = resolveTheme(preference);
  document.documentElement.setAttribute("data-theme", theme);
  const ground = theme === "dark" ? "#0c1211" : "#dfe7e3";
  document.querySelectorAll<HTMLMetaElement>('meta[name="theme-color"]').forEach((meta) => {
    meta.content = ground;
  });
  return theme;
}

/* A tiny store, so the button can read the preference through
 * useSyncExternalStore rather than assigning state from an effect. The server
 * snapshot is "system" because the page is prerendered at build time, where no
 * stored choice exists; the inline bootstrap has already painted the right
 * colours by the time this reconciles. */
const listeners = new Set<() => void>();

export function subscribeToPreference(onChange: () => void): () => void {
  listeners.add(onChange);
  // Another tab changing the choice should move this one too.
  window.addEventListener("storage", onChange);
  return () => {
    listeners.delete(onChange);
    window.removeEventListener("storage", onChange);
  };
}

export const preferenceSnapshot = (): ThemePreference => read();
export const serverPreferenceSnapshot = (): ThemePreference => "system";

export function writePreference(preference: ThemePreference): void {
  try {
    if (preference === "system") localStorage.removeItem(THEME_STORAGE_KEY);
    else localStorage.setItem(THEME_STORAGE_KEY, preference);
  } catch {
    // The choice still applies for this visit; it just will not persist.
  }
  applyTheme(preference);
  listeners.forEach((listener) => listener());
}
