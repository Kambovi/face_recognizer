import { useRef } from "react";
import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable,
} from "@tanstack/react-table";
import { useVirtualizer } from "@tanstack/react-virtual";

interface DataTableProps<T> {
  data: T[];
  columns: ColumnDef<T, unknown>[];
  emptyMessage?: string;
  rowHeight?: number;
  maxBodyHeight?: number;
  getRowId?: (row: T) => string;
}

// Shared virtualized table used by Employees / Unknowns / Analytics -- the
// spec calls for @tanstack/react-table + react-virtual specifically so large
// employee/event lists (100+ rows, growing over time) never render every
// row's DOM node at once.
export function DataTable<T>({
  data,
  columns,
  emptyMessage = "No rows to show.",
  rowHeight = 44,
  maxBodyHeight = 480,
  getRowId,
}: DataTableProps<T>): JSX.Element {
  const parentRef = useRef<HTMLDivElement>(null);

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    getRowId: getRowId ? (row) => getRowId(row) : undefined,
  });

  const rows = table.getRowModel().rows;

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

  return (
    <div className="overflow-hidden rounded-lg border border-gray-200 bg-white shadow-sm">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-left text-sm">
          <thead className="border-b border-gray-200 bg-gray-50 text-xs font-medium uppercase tracking-wide text-gray-500">
            {table.getHeaderGroups().map((headerGroup) => (
              <tr key={headerGroup.id}>
                {headerGroup.headers.map((header) => (
                  <th key={header.id} className="px-4 py-3">
                    {header.isPlaceholder ? null : flexRender(header.column.columnDef.header, header.getContext())}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
        </table>
      </div>
      {/* Explicit height, not just maxHeight: react-virtual renders nothing
          while its scroll container measures 0px tall, and a container sized
          only by its (not-yet-rendered) rows IS 0px tall -- so pages using
          this table (Unknowns, Employees) showed a header and no rows. */}
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ maxHeight: maxBodyHeight, height: rows.length > 0 ? Math.min(totalSize, maxBodyHeight) : undefined }}
      >
        {rows.length === 0 ? (
          <div className="px-4 py-8 text-center text-sm text-gray-500">{emptyMessage}</div>
        ) : (
          <table className="w-full min-w-[640px] text-left text-sm">
            <tbody>
              {paddingTop > 0 && (
                <tr>
                  <td style={{ height: paddingTop }} />
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
                  <td style={{ height: paddingBottom }} />
                </tr>
              )}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
