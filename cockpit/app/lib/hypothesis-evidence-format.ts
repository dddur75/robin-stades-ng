const evidenceNumber = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
});

const signedEvidenceNumber = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  signDisplay: "always",
});

const evidencePercent = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  style: "percent",
});

const signedEvidencePercent = new Intl.NumberFormat("fr-FR", {
  maximumFractionDigits: 2,
  minimumFractionDigits: 2,
  signDisplay: "always",
  style: "percent",
});

export function formatEvidenceNumber(value: number) {
  return evidenceNumber.format(value);
}

export function formatEvidencePercent(
  value: number,
  signed = false,
) {
  return (signed ? signedEvidencePercent : evidencePercent).format(value);
}

export function formatEvidenceUnits(
  value: number,
  signed = false,
) {
  return `${
    signed ? signedEvidenceNumber.format(value) : evidenceNumber.format(value)
  } u`;
}
