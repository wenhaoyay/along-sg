"use client";

import { useEffect, useSyncExternalStore } from "react";
import { Monitor, Moon, Sun } from "lucide-react";

import {
  applyTheme,
  preferenceSnapshot,
  serverPreferenceSnapshot,
  subscribeToPreference,
  writePreference,
  type ThemePreference,
} from "../theme";

const ORDER: ThemePreference[] = ["system", "light", "dark"];

const LABEL: Record<ThemePreference, string> = {
  system: "Theme: match device",
  light: "Theme: light",
  dark: "Theme: dark",
};

const SHORT: Record<ThemePreference, string> = { system: "Auto", light: "Light", dark: "Dark" };
const ICON = { system: Monitor, light: Sun, dark: Moon };

export function ThemeToggle() {
  const preference = useSyncExternalStore(
    subscribeToPreference,
    preferenceSnapshot,
    serverPreferenceSnapshot,
  );

  useEffect(() => {
    // Also on mount: the inline bootstrap sets data-theme but cannot retint
    // <meta name="theme-color">, whose media attributes still follow the
    // system scheme. Without this, reloading with an override left the address
    // bar light behind a dark page.
    applyTheme(preference);
    // While following the device, track it live - a phone switching to dark at
    // sunset should carry the page with it.
    if (preference !== "system") return;
    const query = window.matchMedia("(prefers-color-scheme: dark)");
    const sync = () => applyTheme("system");
    query.addEventListener("change", sync);
    return () => query.removeEventListener("change", sync);
  }, [preference]);

  const Icon = ICON[preference];
  return (
    <button
      type="button"
      className="theme-toggle icon-link"
      onClick={() => writePreference(ORDER[(ORDER.indexOf(preference) + 1) % ORDER.length])}
      aria-label={`${LABEL[preference]}. Change theme.`}
      title={LABEL[preference]}
      data-theme-preference={preference}
    >
      <Icon size={17} aria-hidden="true" />
      <span>{SHORT[preference]}</span>
    </button>
  );
}
