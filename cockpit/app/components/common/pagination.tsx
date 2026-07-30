import Link from "next/link";

import {
  DEFAULT_EXPERIENCE_PAGE_SIZE,
  EXPERIENCE_PAGE_SIZES,
  type ExperiencePageSize,
  type PaginationContract,
} from "../../lib/contracts/experience-v12";
import {
  canonicalizeSearchParams,
  mergeSearchParams,
} from "../../lib/query-params";

export type PaginationItem = number | "ellipsis";

export function paginationItems(
  page: number,
  totalPages: number,
  siblingCount = 1,
): PaginationItem[] {
  const safeTotal = Math.max(1, Math.trunc(totalPages));
  const current = Math.min(Math.max(1, Math.trunc(page) || 1), safeTotal);
  const siblings = Math.max(0, Math.trunc(siblingCount));
  const visible = new Set<number>([1, safeTotal]);
  for (
    let candidate = current - siblings;
    candidate <= current + siblings;
    candidate += 1
  ) {
    if (candidate >= 1 && candidate <= safeTotal) visible.add(candidate);
  }

  const ordered = [...visible].sort((left, right) => left - right);
  const items: PaginationItem[] = [];
  ordered.forEach((value, index) => {
    const previous = ordered[index - 1];
    if (previous != null && value - previous > 1) items.push("ellipsis");
    items.push(value);
  });
  return items;
}

export function paginationHref(
  pathname: string,
  current: URLSearchParams,
  page: number,
  pageSize: ExperiencePageSize,
) {
  const params = mergeSearchParams(current, {
    page: page > 1 ? page : null,
    taille:
      pageSize === DEFAULT_EXPERIENCE_PAGE_SIZE ? null : String(pageSize),
  });
  const query = params.toString();
  return query ? `${pathname}?${query}` : pathname;
}

export function Pagination({
  ariaLabel = "Pagination",
  pagination,
  pathname,
  searchParams = new URLSearchParams(),
  showPageSize = true,
}: {
  ariaLabel?: string;
  pagination: PaginationContract;
  pathname: string;
  searchParams?: URLSearchParams;
  showPageSize?: boolean;
}) {
  const canonical = canonicalizeSearchParams(searchParams);
  const items = paginationItems(
    pagination.page,
    pagination.totalPages,
  );

  return (
    <nav aria-label={ariaLabel} className="pagination">
      <p aria-live="polite" className="pagination-summary">
        {pagination.totalItems === 0
          ? "Aucun résultat"
          : `${pagination.from} à ${pagination.to} sur ${pagination.totalItems}`}
      </p>
      <div className="pagination-pages">
        {pagination.hasPrevious ? (
          <Link
            aria-label="Page précédente"
            href={paginationHref(
              pathname,
              canonical,
              pagination.page - 1,
              pagination.pageSize,
            )}
            rel="prev"
          >
            Précédente
          </Link>
        ) : (
          <span aria-disabled="true">Précédente</span>
        )}

        {items.map((item, index) =>
          item === "ellipsis" ? (
            <span aria-hidden="true" key={`ellipsis-${index}`}>
              …
            </span>
          ) : (
            <Link
              aria-current={
                item === pagination.page ? "page" : undefined
              }
              aria-label={`Page ${item}`}
              href={paginationHref(
                pathname,
                canonical,
                item,
                pagination.pageSize,
              )}
              key={item}
            >
              {item}
            </Link>
          ),
        )}

        {pagination.hasNext ? (
          <Link
            aria-label="Page suivante"
            href={paginationHref(
              pathname,
              canonical,
              pagination.page + 1,
              pagination.pageSize,
            )}
            rel="next"
          >
            Suivante
          </Link>
        ) : (
          <span aria-disabled="true">Suivante</span>
        )}
      </div>

      {showPageSize ? (
        <fieldset className="pagination-sizes">
          <legend>Résultats par page</legend>
          {EXPERIENCE_PAGE_SIZES.map((size) => (
            <Link
              aria-current={
                size === pagination.pageSize ? "true" : undefined
              }
              href={paginationHref(pathname, canonical, 1, size)}
              key={size}
            >
              {size}
            </Link>
          ))}
        </fieldset>
      ) : null}
    </nav>
  );
}
