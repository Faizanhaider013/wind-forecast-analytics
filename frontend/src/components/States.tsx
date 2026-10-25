import type { ReactNode } from "react";

/** Centered loading state with a spinner. */
export function LoadingState({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

/** Error panel. `httpStatus` is shown when present to aid debugging. */
export function ErrorState({
  message,
  httpStatus,
  onRetry,
}: {
  message: string;
  httpStatus?: number;
  onRetry?: () => void;
}) {
  return (
    <div className="state state--error" role="alert">
      <span className="state__title">Something went wrong</span>
      <span>{message}</span>
      {httpStatus ? <span>HTTP {httpStatus}</span> : null}
      {onRetry ? (
        <button className="toggle__btn" type="button" onClick={onRetry}>
          Try again
        </button>
      ) : null}
    </div>
  );
}

/** Neutral empty state. */
export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="state" role="status">
      <span className="state__title">{title}</span>
      {children}
    </div>
  );
}
