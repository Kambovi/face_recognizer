import { useEffect, useRef, useState } from "react";
import clsx from "clsx";
import { Bot, ChevronLeft, ChevronRight, Download, Maximize2, Minimize2, RotateCcw, Send, X } from "lucide-react";
import { getChatStatus, sendChat, toApiError } from "../../api/client";
import type { ChatAction, ChatChoice, ChatColumn, ChatReply, ChatReport, ChatRow, ChatStatus } from "../../api/types";

interface Msg {
  id: number;
  role: "user" | "assistant";
  text: string;
  reply?: ChatReply;
  chosen?: boolean;
  error?: boolean;
}

const STORE_KEY = "hr_chat_messages";
const SUGGESTIONS = [
  "Leave policy kya hai?",
  "Is mahine ki attendance: <naam ya Emp ID>",
  "Production department ka pichle mahine ka report",
  "Office timing aur late ka rule?",
];

function loadMsgs(): Msg[] {
  try {
    return JSON.parse(window.sessionStorage.getItem(STORE_KEY) ?? "[]") as Msg[];
  } catch {
    return [];
  }
}

function saveMsgs(m: Msg[]): void {
  try {
    window.sessionStorage.setItem(STORE_KEY, JSON.stringify(m.slice(-40)));
  } catch {
    /* private mode: chat just isn't remembered across reloads */
  }
}

const inr = new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 });

function cell(v: ChatRow[string] | undefined, col: ChatColumn): string {
  if (v === null || v === undefined || v === "") return "-";
  if (col.money && typeof v === "number") return `₹${inr.format(v)}`;
  return String(v);
}

function downloadCsv(report: ChatReport): void {
  const esc = (s: string): string => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const lines = [report.columns.map((c) => esc(c.label)).join(",")];
  for (const r of [...report.rows, ...(report.totals ? [report.totals] : [])]) {
    lines.push(report.columns.map((c) => esc(r[c.key] == null ? "" : String(r[c.key]))).join(","));
  }
  const blob = new Blob(["﻿" + lines.join("\n")], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${report.title.replace(/[^\w-]+/g, "_")}_${report.month}.csv`;
  a.click();
  URL.revokeObjectURL(url);
}

export function ChatWidget(): JSX.Element | null {
  const [status, setStatus] = useState<ChatStatus | null>(null);
  const [open, setOpen] = useState(false);
  const [wide, setWide] = useState(false);
  const [msgs, setMsgs] = useState<Msg[]>(loadMsgs);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    getChatStatus().then(setStatus).catch(() => setStatus(null));
  }, [open]);
  useEffect(() => saveMsgs(msgs), [msgs]);
  useEffect(() => {
    if (open) endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [msgs, busy, open]);
  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);
  // phone: full-screen panel shouldn't let the page behind it scroll
  useEffect(() => {
    if (!open || window.innerWidth >= 640) return;
    const prev = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = prev;
    };
  }, [open]);

  if (!status?.enabled) return null;

  async function ask(text: string, action?: ChatAction, shown?: string): Promise<void> {
    if (busy || (!text.trim() && !action)) return;
    const history = msgs
      .filter((m) => !m.error && m.text)
      .slice(-12)
      .map((m) => ({ role: m.role, content: m.text }));
    const userMsg: Msg = { id: Date.now(), role: "user", text: shown ?? text };
    setMsgs((m) => [...m, userMsg]);
    setDraft("");
    setBusy(true);
    try {
      const reply = await sendChat({ message: action ? "" : text, history: action ? [] : history, action });
      setMsgs((m) => [...m, { id: Date.now() + 1, role: "assistant", text: reply.text, reply }]);
      if (reply.report) setWide(true);
    } catch (e) {
      setMsgs((m) => [...m, { id: Date.now() + 1, role: "assistant", text: toApiError(e).detail, error: true }]);
    } finally {
      setBusy(false);
    }
  }

  function choose(msgId: number, c: ChatChoice): void {
    setMsgs((m) => m.map((x) => (x.id === msgId ? { ...x, chosen: true } : x)));
    const action: ChatAction = {
      type: c.type, kind: c.kind, id: c.id, query: c.query, department: c.department,
      month: c.month, report: c.report, date: c.date, camera: c.camera,
    };
    void ask("", action, c.type === "filter" ? `Department: ${c.label}` : `✓ ${c.label}`);
  }

  function changeMonth(r: ChatReport, by: number): void {
    const step = by < 0 ? r.nav.prev : r.nav.next;
    if (!step) return;
    const { label, ...action } = step;
    void ask("", action as ChatAction, `${r.title} · ${action.date ?? action.month ?? label}`);
  }

  return (
    <>
      {!open && (
        <button
          onClick={() => setOpen(true)}
          className="fixed bottom-4 right-4 z-40 flex items-center gap-2 rounded-full bg-brand-600 py-3 pl-3 pr-4 text-sm font-semibold text-white shadow-lg hover:bg-brand-700 print:hidden"
          aria-label="Open HR assistant"
        >
          <Bot className="h-5 w-5" aria-hidden />
          <span className="hidden sm:inline">Ask HR</span>
        </button>
      )}
      {open && (
        <div
          role="dialog"
          aria-label="HR assistant"
          className={clsx(
            "fixed inset-0 z-50 flex flex-col bg-white print:hidden",
            "sm:inset-auto sm:bottom-4 sm:right-4 sm:h-[min(680px,calc(100vh-2rem))] sm:rounded-2xl sm:border sm:border-gray-200 sm:shadow-2xl",
            wide ? "sm:w-[min(760px,calc(100vw-2rem))]" : "sm:w-[420px]",
          )}
        >
          <header className="flex items-center gap-2 border-b border-gray-100 px-3 py-2.5">
            <span className="flex h-8 w-8 items-center justify-center rounded-full bg-brand-50 text-brand-700">
              <Bot className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0 flex-1 leading-tight">
              <p className="text-sm font-semibold text-gray-900">HR assistant</p>
              <p className="truncate text-[11px] text-gray-500">
                {status.mode === "llm" ? `AI · ${status.model}` : "Basic mode (no AI model set)"} · {status.policy.files.length} policy file
                {status.policy.files.length === 1 ? "" : "s"}
              </p>
            </div>
            <button onClick={() => setMsgs([])} className="rounded-md p-2 text-gray-500 hover:bg-gray-100" title="New chat" aria-label="New chat">
              <RotateCcw className="h-4 w-4" />
            </button>
            <button
              onClick={() => setWide((w) => !w)}
              className="hidden rounded-md p-2 text-gray-500 hover:bg-gray-100 sm:block"
              aria-label={wide ? "Narrow" : "Widen"}
            >
              {wide ? <Minimize2 className="h-4 w-4" /> : <Maximize2 className="h-4 w-4" />}
            </button>
            <button onClick={() => setOpen(false)} className="rounded-md p-2 text-gray-500 hover:bg-gray-100" aria-label="Close">
              <X className="h-5 w-5" />
            </button>
          </header>

          <div className="flex-1 space-y-3 overflow-y-auto overscroll-contain px-3 py-3">
            {msgs.length === 0 && (
              <div className="space-y-3 pt-2">
                <p className="text-sm text-gray-600">
                  Company policy ke baare me poochiye, ya kisi employee / department / camera ka naam ya ID likhiye. Confirm karne ke baad
                  attendance {status.can_see_salary ? "aur salary " : ""}ka summary milega.
                </p>
                <div className="flex flex-wrap gap-2">
                  {SUGGESTIONS.map((s) => (
                    <button
                      key={s}
                      onClick={() => (s.includes("<") ? (setDraft(s.split(":")[0] + ": "), inputRef.current?.focus()) : void ask(s))}
                      className="rounded-full border border-gray-200 bg-gray-50 px-3 py-1.5 text-left text-xs text-gray-700 hover:bg-gray-100"
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            )}
            {msgs.map((m) => (
              <MessageView key={m.id} m={m} onChoose={(c) => choose(m.id, c)} onMonth={changeMonth} busy={busy} />
            ))}
            {busy && (
              <div className="flex gap-1 px-2 py-2" aria-label="Thinking">
                {[0, 1, 2].map((i) => (
                  <span key={i} className="h-2 w-2 animate-bounce rounded-full bg-gray-300" style={{ animationDelay: `${i * 120}ms` }} />
                ))}
              </div>
            )}
            <div ref={endRef} />
          </div>

          <form
            onSubmit={(e) => {
              e.preventDefault();
              void ask(draft);
            }}
            className="flex items-end gap-2 border-t border-gray-100 p-2.5 pb-[max(0.625rem,env(safe-area-inset-bottom))]"
          >
            <textarea
              ref={inputRef}
              value={draft}
              rows={1}
              maxLength={2000}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  void ask(draft);
                }
              }}
              placeholder="Naam, Emp ID ya sawaal…"
              className="max-h-32 min-h-[42px] flex-1 resize-none rounded-xl border border-gray-300 px-3 py-2.5 text-base focus:border-brand-500 focus:outline-none focus:ring-2 focus:ring-brand-500/20 sm:text-sm"
            />
            <button
              type="submit"
              disabled={busy || !draft.trim()}
              className="flex h-[42px] w-[42px] items-center justify-center rounded-xl bg-brand-600 text-white hover:bg-brand-700 disabled:opacity-40"
              aria-label="Send"
            >
              <Send className="h-4 w-4" />
            </button>
          </form>
        </div>
      )}
    </>
  );
}

function MessageView({
  m,
  onChoose,
  onMonth,
  busy,
}: {
  m: Msg;
  onChoose: (c: ChatChoice) => void;
  onMonth: (r: ChatReport, by: number) => void;
  busy: boolean;
}): JSX.Element {
  if (m.role === "user") {
    return (
      <div className="flex justify-end">
        <p className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-br-md bg-brand-600 px-3 py-2 text-sm text-white">{m.text}</p>
      </div>
    );
  }
  const r = m.reply;
  return (
    <div className="space-y-2">
      {r?.notice && <p className="rounded-lg bg-amber-50 px-3 py-2 text-xs text-amber-800">{r.notice}</p>}
      {!r?.report && (
        <p
          className={clsx(
            "max-w-[92%] whitespace-pre-wrap rounded-2xl rounded-bl-md px-3 py-2 text-sm",
            m.error ? "bg-red-50 text-red-700" : "bg-gray-100 text-gray-800",
          )}
        >
          {m.text}
        </p>
      )}
      {r && r.choices.length > 0 && (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {r.choices.map((c) => (
            <button
              key={`${c.type}-${c.kind}-${c.id ?? c.department}`}
              onClick={() => onChoose(c)}
              disabled={m.chosen || busy}
              className="rounded-xl border border-gray-200 bg-white px-3 py-2 text-left hover:border-brand-400 hover:bg-brand-50 disabled:cursor-default disabled:opacity-50 disabled:hover:border-gray-200 disabled:hover:bg-white"
            >
              <span className="block truncate text-sm font-medium text-gray-900">{c.label}</span>
              <span className="block truncate text-xs text-gray-500">{c.sub}</span>
            </button>
          ))}
        </div>
      )}
      {r?.report && <ReportCard report={r.report} onMonth={onMonth} busy={busy} />}
      {r && r.sources.length > 0 && (
        <details className="text-xs text-gray-500">
          <summary className="cursor-pointer select-none">Sources ({[...new Set(r.sources.map((s) => s.source))].join(", ")})</summary>
          <ul className="mt-1 space-y-1">
            {r.sources.map((s) => (
              <li key={`${s.source}-${s.passage}`} className="rounded-md bg-gray-50 p-2">
                <span className="font-medium text-gray-700">
                  {s.source} · part {s.passage}
                </span>
                <span className="mt-0.5 block whitespace-pre-wrap">{s.snippet}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

function Table({ columns, rows, totals }: { columns: ChatColumn[]; rows: ChatRow[]; totals?: ChatRow | null }): JSX.Element {
  return (
    <div className="overflow-x-auto rounded-lg border border-gray-200">
      <table className="min-w-full text-xs">
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            {columns.map((c, i) => (
              <th
                key={c.key}
                className={clsx("whitespace-nowrap px-2 py-1.5 text-left font-medium", i === 0 && "sticky left-0 bg-gray-50")}
              >
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-100">
          {rows.map((row, ri) => (
            <tr key={ri}>
              {columns.map((c, i) => (
                <td
                  key={c.key}
                  className={clsx(
                    "whitespace-nowrap px-2 py-1.5 tabular-nums text-gray-800",
                    i === 0 && "sticky left-0 bg-white",
                    c.key === "absent" && Number(row[c.key]) > 0 && "text-red-600",
                    c.key === "status" && row[c.key] === "A" && "font-semibold text-red-600",
                  )}
                >
                  {cell(row[c.key], c)}
                </td>
              ))}
            </tr>
          ))}
          {totals && (
            <tr className="bg-gray-50 font-semibold">
              {columns.map((c, i) => (
                <td key={c.key} className={clsx("whitespace-nowrap px-2 py-1.5 tabular-nums", i === 0 && "sticky left-0 bg-gray-50")}>
                  {c.key === "emp_code" ? "" : cell(totals[c.key], c)}
                </td>
              ))}
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}

function ReportCard({ report, onMonth, busy }: { report: ChatReport; onMonth: (r: ChatReport, by: number) => void; busy: boolean }): JSX.Element {
  const atLatest = !report.nav?.next;
  return (
    <div className="space-y-2 rounded-2xl border border-gray-200 bg-white p-3 shadow-sm">
      <div className="flex flex-wrap items-center gap-2">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold text-gray-900">{report.title}</p>
          <p className="text-xs text-gray-500">{report.month_label}</p>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={() => onMonth(report, -1)} disabled={busy || !report.nav?.prev} className="rounded-md border border-gray-200 p-1.5 hover:bg-gray-50" aria-label={report.nav?.prev?.label ?? "Previous"}>
            <ChevronLeft className="h-4 w-4" />
          </button>
          <button
            onClick={() => onMonth(report, 1)}
            disabled={busy || atLatest}
            className="rounded-md border border-gray-200 p-1.5 hover:bg-gray-50 disabled:opacity-40"
            aria-label={report.nav?.next?.label ?? "Next"}
          >
            <ChevronRight className="h-4 w-4" />
          </button>
          {report.rows.length > 0 && (
            <button onClick={() => downloadCsv(report)} className="rounded-md border border-gray-200 p-1.5 hover:bg-gray-50" aria-label="Download CSV" title="Download CSV">
              <Download className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
      <p className="text-sm text-gray-700">{report.summary}</p>
      {report.rows.length > 0 && <Table columns={report.columns} rows={report.rows} totals={report.totals} />}
      {report.salary_hidden && <p className="text-[11px] text-gray-400">Salary columns are visible to admins only.</p>}
      {report.details && report.details.rows.length > 0 && (
        <details>
          <summary className="cursor-pointer select-none text-xs font-medium text-brand-700">Day-wise detail</summary>
          <div className="mt-2 max-h-72 overflow-y-auto">
            <Table columns={report.details.columns} rows={report.details.rows} />
          </div>
        </details>
      )}
      {report.report === "attendance" && (
        <p className="text-[11px] text-gray-400">
          Codes: P present · HD half day · A absent · L paid leave · LWP leave without pay · WO weekly off · WOP worked on weekly off
        </p>
      )}
    </div>
  );
}
