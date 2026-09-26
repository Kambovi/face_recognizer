import type { LucideIcon } from "lucide-react";
import { ScanFace, TriangleAlert, UserCheck, UserX, X } from "lucide-react";
import clsx from "clsx";
import { KPI_LABELS, KPI_ORDER, type KPIFilterType } from "./model";
import { useProfile } from "../../profile/ProfileContext";

// Full class strings (no interpolation) so Tailwind's JIT can see them.
const KPI_CONFIG: Record<
  KPIFilterType,
  { label: string; hint: string; Icon: LucideIcon; iconWrap: string; active: string; bar: string }
> = {
  KNOWN_PRESENT: {
    label: KPI_LABELS.KNOWN_PRESENT,
    hint: "Recognised employees",
    Icon: UserCheck,
    iconWrap: "bg-emerald-50 text-emerald-600",
    active: "border-emerald-500 ring-2 ring-emerald-500/20 shadow-md",
    bar: "bg-emerald-500",
  },
  UNKNOWN_PRESENT: {
    label: KPI_LABELS.UNKNOWN_PRESENT,
    hint: "Unregistered faces seen",
    Icon: ScanFace,
    iconWrap: "bg-sky-50 text-sky-600",
    active: "border-sky-500 ring-2 ring-sky-500/20 shadow-md",
    bar: "bg-sky-500",
  },
  ABSENT: {
    label: KPI_LABELS.ABSENT,
    hint: "Active employees not seen",
    Icon: UserX,
    iconWrap: "bg-rose-50 text-rose-600",
    active: "border-rose-500 ring-2 ring-rose-500/20 shadow-md",
    bar: "bg-rose-500",
  },
  EXCEPTION: {
    label: KPI_LABELS.EXCEPTION,
    hint: "Late, missing OUT, liveness…",
    Icon: TriangleAlert,
    iconWrap: "bg-amber-50 text-amber-600",
    active: "border-amber-500 ring-2 ring-amber-500/20 shadow-md",
    bar: "bg-amber-500",
  },
};

interface KpiCardsProps {
  counts: Record<KPIFilterType, number>;
  active: KPIFilterType | null;
  onToggle: (kpi: KPIFilterType) => void;
}

export function KpiCards({ counts, active, onToggle }: KpiCardsProps): JSX.Element {
  const profile = useProfile();
  const people = profile.person_label_plural.toLowerCase();
  const hints: Record<KPIFilterType, string> = {
    KNOWN_PRESENT: `Recognised ${people}`,
    UNKNOWN_PRESENT: "Faces not registered yet — click Identify",
    ABSENT: `Active ${people} not seen`,
    EXCEPTION: "Late, missing OUT, liveness…",
  };
  // Share of people-rows (Exception overlaps the other three, so it is
  // shown relative to the same base rather than summed in).
  const base = counts.KNOWN_PRESENT + counts.UNKNOWN_PRESENT + counts.ABSENT;
  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
      {KPI_ORDER.map((kpi) => {
        const cfg = KPI_CONFIG[kpi];
        const isActive = active === kpi;
        const pct = base ? Math.min(100, Math.round((counts[kpi] / base) * 100)) : 0;
        return (
          <button
            key={kpi}
            type="button"
            onClick={() => onToggle(kpi)}
            aria-pressed={isActive}
            title={isActive ? "Click again to show all records" : `Show only ${cfg.label}`}
            className={clsx(
              "flex flex-col gap-4 rounded-xl border bg-white p-4 text-left transition-all",
              "focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500/40",
              isActive ? cfg.active : "border-gray-200 shadow-sm hover:-translate-y-0.5 hover:shadow-md",
              active !== null && !isActive && "opacity-60 hover:opacity-100",
            )}
          >
            <div className="flex items-start justify-between">
              <span className={clsx("rounded-lg p-2", cfg.iconWrap)}>
                <cfg.Icon className="h-5 w-5" aria-hidden />
              </span>
              {isActive ? (
                <span className="inline-flex items-center gap-1 rounded-full bg-gray-900 px-2 py-0.5 text-[11px] font-medium text-white">
                  Filtering <X className="h-3 w-3" aria-hidden />
                </span>
              ) : (
                <span className="text-xs tabular-nums text-gray-400">{pct}%</span>
              )}
            </div>
            <div>
              <p className="text-3xl font-semibold tabular-nums tracking-tight text-gray-900">{counts[kpi]}</p>
              <p className="mt-0.5 text-sm font-medium text-gray-700">{cfg.label}</p>
              <p className="text-xs text-gray-500">{hints[kpi]}</p>
            </div>
            <div className="h-1 w-full overflow-hidden rounded-full bg-gray-100">
              <div className={clsx("h-full rounded-full transition-all", cfg.bar)} style={{ width: `${pct}%` }} />
            </div>
          </button>
        );
      })}
    </div>
  );
}
