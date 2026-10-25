/** A small accessible "?" tooltip for concise metric explanations. */
export function InfoTip({ text, label }: { text: string; label?: string }) {
  return (
    <span className="infotip">
      <span
        className="infotip__icon"
        tabIndex={0}
        role="img"
        aria-label={label ? `${label}: ${text}` : text}
      >
        ?
      </span>
      <span className="infotip__bubble" role="tooltip">
        {text}
      </span>
    </span>
  );
}
