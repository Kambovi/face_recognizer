import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Bell, Check, ShieldAlert, Smartphone } from "lucide-react";
import clsx from "clsx";
import { ackAlert, ackAllAlerts, getAlertCount, listAlerts } from "../../api/client";
import type { AlertOut } from "../../api/types";
import { AuthImage } from "../AuthImage";
import { formatTime } from "../../utils/format";

const POLL_MS = 15_000;

/** Short two-tone beep so a guard desk hears a watchlist hit. */
function beep(): void {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    [880, 660].forEach((freq, i) => {
      const o = ctx.createOscillator();
      const g = ctx.createGain();
      o.frequency.value = freq;
      g.gain.value = 0.08;
      o.connect(g);
      g.connect(ctx.destination);
      o.start(ctx.currentTime + i * 0.18);
      o.stop(ctx.currentTime + i * 0.18 + 0.15);
    });
    window.setTimeout(() => void ctx.close(), 800);
  } catch {
    /* audio blocked until the user interacts with the page -- fine */
  }
}

export function AlertBell(): JSX.Element {
  const [count, setCount] = useState(0);
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<AlertOut[]>([]);
  const last = useRef<string | null>(null);
  const box = useRef<HTMLDivElement>(null);

  const poll = useCallback(() => {
    getAlertCount()
      .then((r) => {
        setCount(r.open);
        if (r.latest_at && last.current && r.latest_at > last.current && r.open > 0) beep();
        last.current = r.latest_at ?? last.current ?? "";
      })
      .catch(() => undefined);
  }, []);

  useEffect(() => {
    poll();
    const t = window.setInterval(poll, POLL_MS);
    return () => window.clearInterval(t);
  }, [poll]);

  useEffect(() => {
    if (!open) return;
    listAlerts(true, 10)
      .then(setItems)
      .catch(() => setItems([]));
    const close = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open, count]);

  async function ack(id: string): Promise<void> {
    await ackAlert(id);
    setItems((prev) => prev.filter((a) => a.id !== id));
    poll();
  }

  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => setOpen((v) => !v)}
        className={clsx(
          "relative rounded-md p-2 hover:bg-gray-100",
          count > 0 ? "text-red-600" : "text-gray-500",
        )}
        aria-label={`Alerts: ${count} open`}
      >
        <Bell className="h-5 w-5" />
        {count > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-[1.1rem] rounded-full bg-red-600 px-1 text-center text-[10px] font-bold leading-[1.1rem] text-white">
            {count > 99 ? "99+" : count}
          </span>
        )}
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-[22rem] max-w-[calc(100vw-2rem)] rounded-xl border border-gray-200 bg-white shadow-xl">
          <div className="flex items-center justify-between border-b border-gray-100 px-4 py-2.5">
            <span className="text-sm font-semibold text-gray-900">Alerts</span>
            {items.length > 0 && (
              <button
                onClick={() =>
                  void ackAllAlerts().then(() => {
                    setItems([]);
                    poll();
                  })
                }
                className="text-xs font-medium text-brand-700 hover:underline"
              >
                Acknowledge all
              </button>
            )}
          </div>
          <ul className="max-h-96 divide-y divide-gray-100 overflow-y-auto">
            {items.length === 0 && <li className="px-4 py-6 text-center text-sm text-gray-400">No open alerts.</li>}
            {items.map((a) => (
              <li key={a.id} className="flex gap-3 px-4 py-3">
                <AuthImage
                  path={a.photo_url}
                  alt=""
                  className="h-10 w-10 shrink-0 rounded-md object-cover"
                  fallback={
                    <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md bg-red-50 text-red-600">
                      {a.kind === "spoof" ? <Smartphone className="h-5 w-5" /> : <ShieldAlert className="h-5 w-5" />}
                    </span>
                  }
                />
                <div className="min-w-0 flex-1">
                  <p className="text-sm font-medium text-gray-900">{a.title}</p>
                  {a.detail && <p className="truncate text-xs text-gray-500">{a.detail}</p>}
                  <p className="text-[11px] text-gray-400">{formatTime(a.created_at)}</p>
                </div>
                <button onClick={() => void ack(a.id)} className="self-start rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-emerald-600" aria-label="Acknowledge">
                  <Check className="h-4 w-4" />
                </button>
              </li>
            ))}
          </ul>
          <Link to="/alerts" onClick={() => setOpen(false)} className="block border-t border-gray-100 px-4 py-2 text-center text-xs font-medium text-brand-700 hover:bg-gray-50">
            All alerts &amp; watchlist
          </Link>
        </div>
      )}
    </div>
  );
}
