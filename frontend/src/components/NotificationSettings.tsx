import { useEffect, useState } from "react";
import { MessageCircle } from "lucide-react";
import clsx from "clsx";
import { getNotifyConfig, saveNotifyConfig, sendDailyNow, testNotify, toApiError } from "../api/client";
import type { NotifyConfig } from "../api/types";

const input = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

export function NotificationSettings(): JSX.Element {
  const [cfg, setCfg] = useState<NotifyConfig | null>(null);
  const [token, setToken] = useState("");
  const [numbers, setNumbers] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getNotifyConfig()
      .then((c) => {
        setCfg(c);
        setNumbers(c.recipients.join(", "));
      })
      .catch((e) => setMsg({ ok: false, text: toApiError(e).detail }));
  }, []);

  if (!cfg) return <></>;
  const set = (patch: Partial<NotifyConfig>): void => setCfg({ ...cfg, ...patch });

  async function save(then?: () => Promise<{ sent: boolean; error: string | null; text?: string }>): Promise<void> {
    if (!cfg) return;
    setBusy(true);
    setMsg(null);
    try {
      const saved = await saveNotifyConfig({
        ...cfg,
        recipients: numbers.split(/[,\n]/).map((n) => n.trim()).filter(Boolean),
        ...(token ? { access_token: token } : {}),
      });
      setCfg(saved);
      setNumbers(saved.recipients.join(", "));
      setToken("");
      if (then) {
        const r = await then();
        setMsg(r.sent ? { ok: true, text: r.text ? `Sent: “${r.text}”` : "Test message sent." } : { ok: false, text: r.error ?? "Not sent." });
      } else setMsg({ ok: true, text: "Saved." });
    } catch (e) {
      setMsg({ ok: false, text: toApiError(e).detail });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        <MessageCircle className="h-4 w-4" aria-hidden /> WhatsApp &amp; notifications
      </h2>
      <p className="mb-3 text-xs text-gray-500">
        Alerts go out the moment they happen; a daily summary at the time below; last month&apos;s summary on the 1st.
      </p>
      <div className="mb-3 flex flex-wrap gap-2">
        {(["off", "whatsapp", "webhook"] as const).map((c) => (
          <button
            key={c}
            onClick={() => set({ channel: c })}
            className={clsx(
              "rounded-md border px-3 py-1.5 text-sm",
              cfg.channel === c ? "border-brand-600 bg-brand-50 text-brand-800" : "border-gray-300 text-gray-700",
            )}
          >
            {c === "off" ? "Off" : c === "whatsapp" ? "WhatsApp (Meta Cloud API)" : "Webhook / WhatsApp reseller"}
          </button>
        ))}
      </div>

      {cfg.channel === "whatsapp" && (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
          <label className="text-sm text-gray-700 sm:col-span-2">
            Send to (WhatsApp numbers, comma separated)
            <input className={input} value={numbers} onChange={(e) => setNumbers(e.target.value)} placeholder="98765 43210, 91 99999 00000" />
          </label>
          <label className="text-sm text-gray-700">
            Phone number ID
            <input className={input} value={cfg.phone_number_id} onChange={(e) => set({ phone_number_id: e.target.value })} />
          </label>
          <label className="text-sm text-gray-700">
            Access token
            <input
              className={input}
              type="password"
              value={token}
              placeholder={cfg.access_token_set ? "Saved — leave blank to keep" : "Permanent token from Meta"}
              onChange={(e) => setToken(e.target.value)}
            />
          </label>
          <label className="text-sm text-gray-700">
            Template for alerts
            <input className={input} value={cfg.template_alert} onChange={(e) => set({ template_alert: e.target.value })} placeholder="e.g. security_alert" />
          </label>
          <label className="text-sm text-gray-700">
            Template for daily summary
            <input className={input} value={cfg.template_daily} onChange={(e) => set({ template_daily: e.target.value })} placeholder="e.g. daily_attendance" />
          </label>
          <label className="text-sm text-gray-700">
            Template for monthly summary
            <input className={input} value={cfg.template_monthly} onChange={(e) => set({ template_monthly: e.target.value })} />
          </label>
          <label className="text-sm text-gray-700">
            Template language
            <input className={input} value={cfg.template_language} onChange={(e) => set({ template_language: e.target.value })} />
          </label>
          <p className="text-xs text-gray-500 sm:col-span-2">
            Each template needs one variable ({"{{1}}"}) that receives the message text. Leave a template empty to send plain text
            (WhatsApp only delivers plain text within 24 h of the person messaging you — fine for testing).
          </p>
        </div>
      )}

      {cfg.channel === "webhook" && (
        <label className="block text-sm text-gray-700">
          Webhook URL (receives {"{"}&quot;text&quot;, &quot;kind&quot;{"}"} as JSON)
          <input className={input} value={cfg.webhook_url} onChange={(e) => set({ webhook_url: e.target.value })} placeholder="https://..." />
        </label>
      )}

      {cfg.channel !== "off" && (
        <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-gray-700">
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={cfg.send_alerts} onChange={(e) => set({ send_alerts: e.target.checked })} /> Alerts
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={cfg.send_daily} onChange={(e) => set({ send_daily: e.target.checked })} /> Daily summary at
            <input type="time" className="rounded-md border border-gray-300 px-2 py-1" value={cfg.daily_time} onChange={(e) => set({ daily_time: e.target.value })} />
          </label>
          <label className="flex items-center gap-1.5">
            <input type="checkbox" checked={cfg.send_monthly} onChange={(e) => set({ send_monthly: e.target.checked })} /> Monthly summary
          </label>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-2">
        <button disabled={busy} onClick={() => void save()} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
          Save
        </button>
        {cfg.channel !== "off" && (
          <>
            <button disabled={busy} onClick={() => void save(testNotify)} className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
              Save &amp; send test
            </button>
            <button disabled={busy} onClick={() => void save(sendDailyNow)} className="rounded-md border border-gray-300 px-4 py-2 text-sm text-gray-700 hover:bg-gray-50">
              Send today&apos;s summary now
            </button>
          </>
        )}
      </div>
      {msg && <p className={clsx("mt-2 text-sm", msg.ok ? "text-emerald-700" : "text-red-700")}>{msg.text}</p>}
      {!msg && cfg.last_error && <p className="mt-2 text-xs text-red-600">Last error: {cfg.last_error}</p>}
    </div>
  );
}
