// Apply before styles/React; storage may be unavailable in private/embedded contexts.
try {
  document.documentElement.dataset.theme =
    localStorage.getItem("tramflow.theme.v1") === "light" ? "light" : "dark";
} catch {
  document.documentElement.dataset.theme = "dark";
}

document
  .querySelector("meta[name=theme-color]")
  ?.setAttribute(
    "content",
    document.documentElement.dataset.theme === "light" ? "#ffffff" : "#132330",
  );
