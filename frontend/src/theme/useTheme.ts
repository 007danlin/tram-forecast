import { useState } from "react";
export type Theme = "dark" | "light";
export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() =>
    document.documentElement.dataset.theme === "light" ? "light" : "dark",
  );
  function changeTheme(next: Theme) {
    document.documentElement.dataset.theme = next;
    document
      .querySelector("meta[name=theme-color]")
      ?.setAttribute("content", next === "light" ? "#ffffff" : "#132330");
    try {
      localStorage.setItem("tramflow.theme.v1", next);
    } catch {
      /* Theme still works in memory. */
    }
    setTheme(next);
  }
  return { theme, changeTheme };
}
