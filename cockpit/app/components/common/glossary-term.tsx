import { glossaryEntry } from "../../i18n/glossary";

export function GlossaryTerm({ term }: { term: string }) {
  const entry = glossaryEntry(term);
  if (!entry) return <>{term}</>;
  return (
    <span className="glossary-term" tabIndex={0}>
      {term}
      <span className="glossary-tooltip" role="tooltip">
        <strong>{entry.publicName}</strong>
        {entry.simple}
      </span>
    </span>
  );
}
