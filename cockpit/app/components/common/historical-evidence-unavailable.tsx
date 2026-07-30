import { HistoricalEvidenceUnavailableContent } from "./historical-evidence-unavailable-content";
import styles from "./historical-evidence-unavailable.module.css";

export function HistoricalEvidenceUnavailable({
  code,
  retryHref,
}: {
  code: string;
  retryHref: string;
}) {
  return (
    <HistoricalEvidenceUnavailableContent
      className={styles.state}
      code={code}
      retryHref={retryHref}
    />
  );
}
