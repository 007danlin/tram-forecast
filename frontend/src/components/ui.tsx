import type { ComponentProps } from "react";

export function Button({
  variant = "neutral",
  className = "",
  ...props
}: ComponentProps<"button"> & { variant?: "neutral" | "primary" | "ghost" }) {
  return (
    <button
      type="button"
      className={`button button--${variant} ${className}`}
      {...props}
    />
  );
}

export type IconName =
  | "sun"
  | "moon"
  | "menu"
  | "close"
  | "expand"
  | "home"
  | "play"
  | "pause"
  | "chevron";
const paths: Record<IconName, React.ReactNode> = {
  sun: (
    <>
      <circle cx="12" cy="12" r="4" />
      <path d="M12 2v2m0 16v2M2 12h2m16 0h2M5 5l1.5 1.5m11 11L19 19M5 19l1.5-1.5m11-11L19 5" />
    </>
  ),
  moon: <path d="M20.5 13A8.5 8.5 0 0 1 11 3.5 8.5 8.5 0 1 0 20.5 13Z" />,
  menu: <path d="M4 6h16M4 12h16M4 18h16" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  expand: <path d="M9 3H3v6m12-6h6v6M3 15v6h6m12-6v6h-6" />,
  home: (
    <>
      <path d="m3 11 9-8 9 8M5 9v12h14V9M9 21v-8h6v8" />
    </>
  ),
  play: <path d="m8 5 11 7-11 7Z" />,
  pause: <path d="M8 5v14M16 5v14" />,
  chevron: <path d="m6 9 6 6 6-6" />,
};
export function Icon({ name }: { name: IconName }) {
  return (
    <svg
      className="icon"
      viewBox="0 0 24 24"
      width="20"
      height="20"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths[name]}
    </svg>
  );
}
