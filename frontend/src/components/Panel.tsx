import type { ReactNode } from "react";

/** A titled surface panel used to group charts and tables. */
export function Panel({
  title,
  hint,
  actions,
  children,
}: {
  title: string;
  hint?: string;
  actions?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="panel">
      <div className="panel__head">
        <div>
          <h2 className="panel__title">{title}</h2>
          {hint ? <p className="panel__hint">{hint}</p> : null}
        </div>
        {actions}
      </div>
      <div className="panel__body">{children}</div>
    </section>
  );
}

const WarnIcon = (
  <svg className="banner__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <path
      d="M12 3 2 20h20L12 3Zm0 6v5m0 3h.01"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
    />
  </svg>
);

const InfoIcon = (
  <svg className="banner__icon" width="18" height="18" viewBox="0 0 24 24" fill="none" aria-hidden="true">
    <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.8" />
    <path d="M12 11v5m0-8h.01" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
  </svg>
);

/** Inline banner for coverage warnings and contextual info. */
export function Banner({
  variant,
  children,
  role,
}: {
  variant: "warn" | "info";
  children: ReactNode;
  role?: "status" | "alert";
}) {
  return (
    <div className={`banner banner--${variant}`} role={role ?? "status"}>
      {variant === "warn" ? WarnIcon : InfoIcon}
      <div>{children}</div>
    </div>
  );
}
