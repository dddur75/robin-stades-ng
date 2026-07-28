"use client";

import { useMemo, useState } from "react";

import { t } from "../../i18n";

export type TableColumn<Row> = {
  key: keyof Row & string;
  label: string;
  format?: (value: Row[keyof Row], row: Row) => string;
};

function csvCell(value: unknown) {
  return `"${String(value ?? "").replaceAll('"', '""')}"`;
}

export function RichTable<Row extends Record<string, unknown>>({
  caption,
  rows,
  columns,
  filename,
}: {
  caption: string;
  rows: Row[];
  columns: TableColumn<Row>[];
  filename: string;
}) {
  const [query, setQuery] = useState("");
  const [sortKey, setSortKey] = useState(columns[0]?.key ?? "");
  const [ascending, setAscending] = useState(true);
  const [hidden, setHidden] = useState<string[]>([]);

  const visibleColumns = columns.filter((column) => !hidden.includes(column.key));
  const visibleRows = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase("fr-FR");
    const filtered = normalized
      ? rows.filter((row) =>
          columns.some((column) =>
            String(row[column.key] ?? "")
              .toLocaleLowerCase("fr-FR")
              .includes(normalized),
          ),
        )
      : rows;
    return [...filtered].sort((left, right) => {
      const a = String(left[sortKey] ?? "");
      const b = String(right[sortKey] ?? "");
      return a.localeCompare(b, "fr-FR", { numeric: true }) * (ascending ? 1 : -1);
    });
  }, [ascending, columns, query, rows, sortKey]);

  const exportCsv = () => {
    const content = [
      visibleColumns.map((column) => csvCell(column.label)).join(";"),
      ...visibleRows.map((row) =>
        visibleColumns
          .map((column) =>
            csvCell(
              column.format
                ? column.format(row[column.key], row)
                : row[column.key],
            ),
          )
          .join(";"),
      ),
    ].join("\r\n");
    const url = URL.createObjectURL(
      new Blob([`\uFEFF${content}`], { type: "text/csv;charset=utf-8" }),
    );
    const link = document.createElement("a");
    link.href = url;
    link.download = filename;
    link.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="rich-table">
      <div className="table-tools">
        <label>
          <span>{t("action.search")}</span>
          <input
            onChange={(event) => setQuery(event.target.value)}
            placeholder={`${t("action.search")}…`}
            type="search"
            value={query}
          />
        </label>
        <details>
          <summary>{t("table.columns")}</summary>
          <div className="column-picker">
            {columns.map((column) => (
              <label key={column.key}>
                <input
                  checked={!hidden.includes(column.key)}
                  onChange={() =>
                    setHidden((current) =>
                      current.includes(column.key)
                        ? current.filter((key) => key !== column.key)
                        : [...current, column.key],
                    )
                  }
                  type="checkbox"
                />
                {column.label}
              </label>
            ))}
          </div>
        </details>
        <button className="secondary-button" onClick={exportCsv} type="button">
          {t("action.exportCsv")}
        </button>
      </div>
      <div className="table-scroll" tabIndex={0}>
        <table>
          <caption>{caption}</caption>
          <thead>
            <tr>
              {visibleColumns.map((column) => (
                <th key={column.key} scope="col">
                  <button
                    onClick={() => {
                      if (sortKey === column.key) setAscending((value) => !value);
                      else {
                        setSortKey(column.key);
                        setAscending(true);
                      }
                    }}
                    type="button"
                  >
                    {column.label}
                    {sortKey === column.key ? (
                      <span aria-label={ascending ? "croissant" : "décroissant"}>
                        {ascending ? " ↑" : " ↓"}
                      </span>
                    ) : null}
                  </button>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {visibleRows.map((row, rowIndex) => (
              <tr key={rowIndex}>
                {visibleColumns.map((column) => (
                  <td key={column.key} data-label={column.label}>
                    {column.format
                      ? column.format(row[column.key], row)
                      : String(row[column.key] ?? "—")}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!visibleRows.length ? <p className="table-empty">{t("table.noRows")}</p> : null}
    </div>
  );
}
