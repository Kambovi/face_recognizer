import { useRef, useState } from "react";
import {
  type Column,
  type ColumnDef,
  type ColumnFiltersState,
  type SortingState,
  flexRender,
  getCoreRowModel,
  getFacetedRowModel,
  getFacetedUniqueValues,
  getFilteredRowModel,
  getSortedRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";
import { ArrowDown, ArrowUp, ArrowUpDown, X } from "lucide-react";

/** Per-column options, set as `meta` on a ColumnDef:
 *   filter: "text" (default for data columns) | "select" (dropdown of values; also set
 *           filterFn: "equalsString" on the column) | false
 *   filterLabel: (value) => text shown in the select for a raw value */
export interface DataColumnMeta {
  filter?: "text" | "select" | false;
  filterLabel?: (value: string) => string;
}

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  emptyMessage?: string;
  rowHeight?: number;
  maxBodyHeight?: number;
  getRowId?: (row: T) => string;
  /** Click a header to sort (default on). Columns without an accessor never sort. */
  sortable?: boolean;
  /** Show a filter row under the headers (default off). */
  filterable?: boolean;
  initialSort?: SortingState;
}

function metaOf(column: { columnDef: { meta?: unknown } } | undefined): DataColumnMeta {
  return (column?.columnDef.meta ?? {}) as DataColumnMeta;
}

// Shared virtualized table used by Employees / Unknowns / Analytics / Dashboard
// events -- @tanstack/react-table + react-virtual so large lists never render
// every row's DOM node at once. One <table> with a sticky header (before
// 2026-09-29 header and body were two tables whose columns could drift apart).
export function DataTable<T>({
  data,
  columns,
  emptyMessage = "No rows to show.",
  rowHeight = 44,
  maxBodyHeight = 480,
  getRowId,
  sortable = true,
  filterable = false,
  initialSort = [],
}: DataTableProps<T>): JSX.Element {
  const parentRef = useRef<HTMLDivElement>(null);
  const [sorting, setSorting] = useState<SortingState>(initialSort);
  const [filters, setFilters] = useState<ColumnFiltersState>([]);

  const table = useReactTable({
    data,
    columns,
    state: { sorting, columnFilters: filters },
    onSortingChange: setSorting,
    onColumnFiltersChange: setFilters,
    enableSorting: sortable,
    enableColumnFilters: filterable,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getFilteredRowModel: getFilteredRowModel(),
    getFacetedRowModel: getFacetedRowModel(),
    getFacetedUniqueValues: getFacetedUniqueValues(),
    // text filter = case-insensitive "contains"; select columns set filterFn: "equalsString"
    defaultColumn: { filterFn: "includesString", sortUndefined: "last" },
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
  });

  const rows = table.getRowModel().rows;
  const total = data.length;

  const virtualizer = useVirtualizer({
    count: rows.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => rowHeight,
    overscan: 12,
  });

  const virtualRows = virtualizer.getVirtualItems();
  const totalSize = virtualizer.getTotalSize();
  const paddingTop = virtualRows.length > 0 ? (virtualRows[0]?.start ?? 0) : 0;
  const paddingBottom = virtualRows.length > 0 ? totalSize - (virtualRows[virtualRows.length - 1]?.end ?? 0) : 0;
  const colCount = table.getVisibleLeafColumns().length;
  const headerHeight = filterable ? 84 : 44;

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      {filterable && filters.length > 0 && (
        <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2 text-xs text-gray-600">
          <span>
            Showing <strong>{rows.length}</strong> of {total}
          </span>
          <button onClick={() => setFilters([])} className="inline-flex items-center gap-1 text-brand-700 hover:underline">
            <X className="h-3 w-3" aria-hidden /> Clear filters
          </button>
        </div>
      )}
      {/* Explicit height, not just maxHeight: react-virtual renders nothing
          while its scroll container measures 0px tall. */}
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ maxHeight: maxBodyHeight, height: rows.length > 0 ? Math.min(totalSize + headerHeight, maxBodyHeight) : undefined }}
      >
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="sticky top-0 z-10 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500 shadow-[0_1px_0_#e5e7eb]">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => {
                  const canSort = header.column.getCanSort();
                  const dir = header.column.getIsSorted();
                  const label = flexRender(header.column.columnDef.header, header.getContext());
                  return (
                    <th
                      key={header.id}
                      className="whitespace-nowrap px-4 py-3"
                      aria-sort={dir === "asc" ? "ascending" : dir === "desc" ? "descending" : undefined}
                    >
                      {header.isPlaceholder ? null : canSort ? (
                        <button
                          type="button"
                          onClick={header.column.getToggleSortingHandler()}
                          className="inline-flex items-center gap-1 uppercase hover:text-gray-800"
                          title="Sort"
                        >
                          {label}
                          {dir === "asc" ? (
                            <ArrowUp className="h-3.5 w-3.5 text-brand-600" aria-hidden />
                          ) : dir === "desc" ? (
                            <ArrowDown className="h-3.5 w-3.5 text-brand-600" aria-hidden />
                          ) : (
                            <ArrowUpDown className="h-3.5 w-3.5 text-gray-300" aria-hidden />
                          )}
                        </button>
                      ) : (
                        label
                      )}
                    </th>
                  );
                })}
              </tr>
            ))}
            {filterable && (
              <tr>
                {table.getVisibleLeafColumns().map((column) => (
                  <th key={column.id} className="px-4 pb-2 pt-0 font-normal normal-case tracking-normal">
                    {column.getCanFilter() && metaOf(column).filter !== false ? <ColumnFilter column={column} /> : null}
                  </th>
                ))}
              </tr>
            )}
          </thead>
          <tbody>
            {rows.length === 0 ? (
              <tr>
                <td colSpan={colCount} className="px-4 py-8 text-center text-sm text-gray-500">
                  {total > 0 && filters.length > 0 ? "No rows match the filters." : emptyMessage}
                </td>
              </tr>
            ) : (
              <>
                {paddingTop > 0 && (
                  <tr>
                    <td colSpan={colCount} style={{ height: paddingTop }} />
                  </tr>
                )}
                {virtualRows.map((virtualRow) => {
                  const row = rows[virtualRow.index];
                  if (!row) return null;
                  return (
                    <tr
                      key={row.id}
                      data-index={virtualRow.index}
                      ref={virtualizer.measureElement}
                      className="border-b border-gray-100 last:border-b-0 hover:bg-gray-50"
                    >
                      {row.getVisibleCells().map((cell) => (
                        <td key={cell.id} className="px-4 py-2.5 align-middle text-gray-700">
                          {flexRender(cell.column.columnDef.cell, cell.getContext())}
                        </td>
                      ))}
                    </tr>
                  );
                })}
                {paddingBottom > 0 && (
                  <tr>
                    <td colSpan={colCount} style={{ height: paddingBottom }} />
                  </tr>
                )}
              </>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ColumnFilter<T>({ column }: { column: Column<T, unknown> }): JSX.Element {
  const meta = metaOf(column);
  const value = (column.getFilterValue() as string | undefined) ?? "";
  const cls =
    "w-full min-w-[6rem] rounded-md border border-gray-200 bg-white px-2 py-1 text-xs text-gray-700 focus:border-brand-400 focus:outline-none";
  const header = typeof column.columnDef.header === "string" ? column.columnDef.header : column.id;
  if (meta.filter === "select") {
    const options = Array.from(column.getFacetedUniqueValues().keys())
      .map((v) => String(v ?? ""))
      .sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    return (
      <select
        value={value}
        onChange={(e) => column.setFilterValue(e.target.value || undefined)}
        className={cls}
        aria-label={`Filter ${header}`}
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {meta.filterLabel ? meta.filterLabel(o) : o || "(blank)"}
          </option>
        ))}
      </select>
    );
  }
  return (
    <input
      value={value}
      onChange={(e) => column.setFilterValue(e.target.value || undefined)}
      placeholder="Filter…"
      className={cls}
      aria-label={`Filter ${header}`}
    />
  );
}
