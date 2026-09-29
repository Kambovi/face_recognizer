import { useEffect, useRef, useState } from "react";
import { CalendarDays, Check, ChevronDown, Cctv, IdCard, X } from "lucide-react";
import clsx from "clsx";
import { buildRange, type DateRange, type DateRangeMode } from "./model";
import { useProfile } from "../../profile/ProfileContext";

// ------------------------------------------------ entry point multi-select ----

interface UnitMultiSelectProps {
  /** All entry points (kiosk / camera ids). */
  options: string[];
  /** null = all selected (new kiosks auto-included). */
  value: string[] | null;
  onChange: (next: string[] | null) => void;
}

export function UnitMultiSelect({ options, value, onChange }: UnitMultiSelectProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selectAllRef = useRef<HTMLInputElement>(null);

  const selected = value ?? options;
  const allSelected = value === null || (options.length > 0 && options.every((o) => value.includes(o)));
  const someSelected = !allSelected && selected.length > 0;

  // `indeterminate` only exists as a DOM property.
  useEffect(() => {
    if (selectAllRef.current) selectAllRef.current.indeterminate = someSelected;
  }, [someSelected, open]);

  useEffect(() => {
    if (!open) return undefined;
    const onDown = (e: MouseEvent): void => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const toggleOne = (id: string): void => {
    const next = selected.includes(id) ? selected.filter((v) => v !== id) : [...selected, id];
    onChange(options.every((o) => next.includes(o)) ? null : next);
  };

  const label = allSelected
    ? "All entry points"
    : selected.length === 0
      ? "No entry point selected"
      : selected.length <= 2
        ? selected.join(", ")
        : `${selected.length} of ${options.length} entry points`;

  return (
    <div ref={rootRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        className="flex w-full items-center gap-2 rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm hover:border-gray-300 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40 md:w-64"
      >
        <Cctv className="h-4 w-4 shrink-0 text-gray-400" aria-hidden />
        <span className={clsx("flex-1 truncate text-left", selected.length === 0 && "text-rose-600")}>{label}</span>
        <ChevronDown className={clsx("h-4 w-4 text-gray-400 transition-transform", open && "rotate-180")} aria-hidden />
      </button>

      {open && (
        <div className="absolute left-0 z-30 mt-2 w-full min-w-[18rem] rounded-xl border border-gray-200 bg-white p-1.5 shadow-lg md:w-72">
          <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm font-medium hover:bg-gray-50">
            <input
              ref={selectAllRef}
              type="checkbox"
              checked={allSelected}
              onChange={() => onChange(allSelected ? [] : null)}
              className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
            />
            Select all
            <span className="ml-auto text-xs font-normal text-gray-400">
              {selected.length}/{options.length}
            </span>
          </label>
          <div className="my-1 h-px bg-gray-100" />
          {options.length === 0 ? (
            <p className="px-2.5 py-3 text-xs text-gray-500">No entry points have reported yet.</p>
          ) : (
            <ul role="listbox" aria-multiselectable="true" className="max-h-64 overflow-y-auto">
              {options.map((id) => {
                const checked = selected.includes(id);
                return (
                  <li key={id} role="option" aria-selected={checked}>
                    <label className="flex cursor-pointer items-center gap-3 rounded-lg px-2.5 py-2 text-sm hover:bg-gray-50">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleOne(id)}
                        className="h-4 w-4 rounded border-gray-300 text-brand-600 focus:ring-brand-500"
                      />
                      <span className="truncate font-mono text-xs text-gray-800">{id}</span>
                      {checked && <Check className="ml-auto h-4 w-4 text-brand-600" aria-hidden />}
                    </label>
                  </li>
                );
              })}
            </ul>
          )}
          <p className="border-t border-gray-100 px-2.5 pb-1 pt-2 text-[11px] leading-snug text-gray-400">
            Absent employees aren&apos;t tied to an entry point, so they stay listed while any entry point is selected.
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------- emp id filter ----

interface EmpCodeFilterProps {
  value: string;
  onChange: (next: string) => void;
}

/** Free-text filter on the employee code (e.g. "EMP-102") -- separate from
 *  Face ID, which is the system-generated id already shown as its own column. */
export function EmpCodeFilter({ value, onChange }: EmpCodeFilterProps): JSX.Element {
  const profile = useProfile();
  return (
    <div className="relative">
      <IdCard className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" aria-hidden />
      <input
        type="text"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={`Filter by ${profile.id_label}`}
        aria-label={`Filter by ${profile.id_label}`}
        className="w-full rounded-lg border border-gray-200 bg-white py-2 pl-9 pr-8 text-sm placeholder:text-gray-400 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-500/20 md:w-48"
      />
      {value && (
        <button
          type="button"
          onClick={() => onChange("")}
          aria-label="Clear employee ID filter"
          className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-0.5 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
        >
          <X className="h-3.5 w-3.5" aria-hidden />
        </button>
      )}
    </div>
  );
}

// ------------------------------------------------------------ date picker ----

const MODES: { id: DateRangeMode; label: string }[] = [
  { id: "day", label: "Day" },
  { id: "month", label: "Month" },
  { id: "year", label: "Year" },
  { id: "custom", label: "Range" },
];

interface DateRangePickerProps {
  value: DateRange;
  onChange: (next: DateRange) => void;
  /** Local "today" (YYYY-MM-DD); nothing after it is selectable. */
  today: string;
}

export function DateRangePicker({ value, onChange, today }: DateRangePickerProps): JSX.Element {
  const input =
    "rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm text-gray-700 focus:border-brand-400 focus:outline-none focus:ring-2 focus:ring-brand-500/20";
  const thisYear = Number(today.slice(0, 4));
  const years = Array.from({ length: 6 }, (_, i) => thisYear - i);

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
      <div className="flex items-center gap-2">
        <CalendarDays className="h-4 w-4 text-gray-400" aria-hidden />
        <div role="tablist" aria-label="Date range type" className="inline-flex rounded-lg bg-gray-100 p-0.5">
          {MODES.map((m) => (
            <button
              key={m.id}
              type="button"
              role="tab"
              aria-selected={value.mode === m.id}
              onClick={() =>
                // Day / Month / Year tabs always open on the current period (today, this
                // month, this year); pick an older one with the input next to them.
                onChange(m.id === "custom" ? buildRange("custom", value.from, value.to) : buildRange(m.id, today))
              }
              className={clsx(
                "rounded-md px-3 py-1.5 text-xs font-medium transition",
                value.mode === m.id ? "bg-white text-gray-900 shadow-sm" : "text-gray-500 hover:text-gray-700",
              )}
            >
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {value.mode === "day" && (
          <input
            type="date"
            aria-label="Date"
            value={value.from}
            max={today}
            onChange={(e) => e.target.value && onChange(buildRange("day", e.target.value))}
            className={input}
          />
        )}
        {value.mode === "month" && (
          <input
            type="month"
            aria-label="Month"
            value={value.from.slice(0, 7)}
            max={today.slice(0, 7)}
            onChange={(e) => e.target.value && onChange(buildRange("month", `${e.target.value}-01`))}
            className={input}
          />
        )}
        {value.mode === "year" && (
          <select
            aria-label="Year"
            value={value.from.slice(0, 4)}
            onChange={(e) => onChange(buildRange("year", `${e.target.value}-01-01`))}
            className={input}
          >
            {years.map((y) => (
              <option key={y} value={y}>
                {y}
              </option>
            ))}
          </select>
        )}
        {value.mode === "custom" && (
          <>
            <input
              type="date"
              aria-label="From date"
              value={value.from}
              max={value.to}
              onChange={(e) => e.target.value && onChange(buildRange("custom", e.target.value, value.to))}
              className={input}
            />
            <span className="text-sm text-gray-400">to</span>
            <input
              type="date"
              aria-label="To date"
              value={value.to}
              min={value.from}
              max={today}
              onChange={(e) => e.target.value && onChange(buildRange("custom", value.from, e.target.value))}
              className={input}
            />
          </>
        )}
        {!(value.from <= today && today <= value.to && value.mode === "day") && (
          <button
            type="button"
            onClick={() => onChange(buildRange("day", today))}
            className="rounded-lg px-2.5 py-2 text-xs font-medium text-brand-600 hover:bg-brand-50"
          >
            Today
          </button>
        )}
      </div>
    </div>
  );
}
