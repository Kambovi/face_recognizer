import { useEffect, useState } from "react";
import { Bot, RefreshCw } from "lucide-react";
import { getChatConfig, reindexPolicy, saveChatConfig, testChatModel, toApiError } from "../api/client";
import type { ChatConfig } from "../api/types";

const input = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm";

const DEFAULT_PROVIDER = { value: "off" as const, label: "None (basic mode)", model: "", hint: "" };
const PROVIDERS: { value: ChatConfig["provider"]; label: string; model: string; hint: string }[] = [
  { value: "off", label: "None (basic mode)", model: "", hint: "No AI: keyword search in policy + name/ID lookup. Works offline." },
  { value: "anthropic", label: "Claude (Anthropic API)", model: "claude-sonnet-4-5", hint: "Cloud. Best answers. Names and policy text go to the API; attendance and salary figures never do." },
  { value: "openai", label: "OpenAI API", model: "gpt-4o-mini", hint: "Cloud. Same data rule as above." },
  { value: "ollama", label: "Ollama (local, on this server)", model: "qwen2.5:7b", hint: "Nothing leaves the premises. Needs Ollama installed and ~8 GB free RAM; use a model with tool support." },
];

export function ChatbotSettings(): JSX.Element {
  const [cfg, setCfg] = useState<ChatConfig | null>(null);
  const [key, setKey] = useState("");
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getChatConfig().then(setCfg).catch((e) => setMsg({ ok: false, text: toApiError(e).detail }));
  }, []);

  if (!cfg) return msg ? <p className="text-sm text-red-600">{msg.text}</p> : <></>;
  const set = (patch: Partial<ChatConfig>): void => setCfg({ ...cfg, ...patch });
  const prov = PROVIDERS.find((p) => p.value === cfg.provider) ?? DEFAULT_PROVIDER;

  async function save(test = false): Promise<void> {
    if (!cfg) return;
    setBusy(true);
    setMsg(null);
    try {
      const saved = await saveChatConfig({ ...cfg, ...(key ? { api_key: key } : {}) });
      setCfg(saved);
      setKey("");
      if (test) {
        const r = await testChatModel();
        setMsg(r.ok ? { ok: true, text: `Model replied: “${r.reply}”` } : { ok: false, text: r.error ?? "No reply" });
      } else setMsg({ ok: true, text: "Saved." });
    } catch (e) {
      setMsg({ ok: false, text: toApiError(e).detail });
    } finally {
      setBusy(false);
    }
  }

  async function reindex(): Promise<void> {
    if (!cfg) return;
    setBusy(true);
    try {
      set({ policy: await reindexPolicy() });
    } catch (e) {
      setMsg({ ok: false, text: toApiError(e).detail });
    } finally {
      setBusy(false);
    }
  }

  const p = cfg.policy;
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <h2 className="mb-1 flex items-center gap-2 text-sm font-semibold uppercase tracking-wide text-gray-500">
        <Bot className="h-4 w-4" aria-hidden /> HR chatbot
      </h2>
      <p className="mb-3 text-xs text-gray-500">
        Answers policy questions from the policy folder, and shows attendance / payroll summaries after the user confirms the person.
        Salaries are shown to admins only.
      </p>

      <label className="mb-3 flex items-center gap-2 text-sm">
        <input type="checkbox" checked={cfg.enabled} onChange={(e) => set({ enabled: e.target.checked })} />
        Show the “Ask HR” button on the dashboard
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block text-xs font-medium text-gray-700">
          AI model provider
          <select
            className={`${input} mt-1`}
            value={cfg.provider}
            onChange={(e) => {
              const next = PROVIDERS.find((x) => x.value === e.target.value) ?? DEFAULT_PROVIDER;
              set({ provider: next.value, model: cfg.model && cfg.provider === next.value ? cfg.model : next.model, base_url: "" });
            }}
          >
            {PROVIDERS.map((x) => (
              <option key={x.value} value={x.value}>
                {x.label}
              </option>
            ))}
          </select>
        </label>
        {cfg.provider !== "off" && (
          <label className="block text-xs font-medium text-gray-700">
            Model name
            <input className={`${input} mt-1`} value={cfg.model} placeholder={prov.model} onChange={(e) => set({ model: e.target.value })} />
          </label>
        )}
        <p className="text-xs text-gray-500 sm:col-span-2">{prov.hint}</p>
        {(cfg.provider === "anthropic" || cfg.provider === "openai") && (
          <label className="block text-xs font-medium text-gray-700 sm:col-span-2">
            API key {cfg.api_key_set && <span className="font-normal text-emerald-700">(saved; leave blank to keep)</span>}
            <input className={`${input} mt-1`} type="password" autoComplete="off" value={key} onChange={(e) => setKey(e.target.value)} />
          </label>
        )}
        {cfg.provider !== "off" && (
          <label className="block text-xs font-medium text-gray-700 sm:col-span-2">
            Server URL <span className="font-normal text-gray-400">(blank = default{cfg.provider === "ollama" ? ", http://localhost:11434/v1" : ""})</span>
            <input className={`${input} mt-1`} value={cfg.base_url} onChange={(e) => set({ base_url: e.target.value })} />
          </label>
        )}
        {cfg.provider !== "off" && (
          <label className="block text-xs font-medium text-gray-700 sm:col-span-2">
            Extra instructions <span className="font-normal text-gray-400">(optional, e.g. “Always reply in Hindi”)</span>
            <textarea className={`${input} mt-1`} rows={2} value={cfg.org_note} onChange={(e) => set({ org_note: e.target.value })} />
          </label>
        )}
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <button onClick={() => save()} disabled={busy} className="rounded-md bg-brand-600 px-4 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-50">
          Save
        </button>
        {cfg.provider !== "off" && (
          <button onClick={() => save(true)} disabled={busy} className="rounded-md border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 disabled:opacity-50">
            Save &amp; test model
          </button>
        )}
      </div>
      {msg && <p className={`mt-2 text-sm ${msg.ok ? "text-emerald-700" : "text-red-600"}`}>{msg.text}</p>}

      <div className="mt-4 rounded-md bg-gray-50 p-3 text-xs text-gray-600">
        <div className="flex items-center justify-between gap-2">
          <p className="font-medium text-gray-800">
            Policy documents: {p.files.length} file{p.files.length === 1 ? "" : "s"}, {p.chunks} passages
          </p>
          <button onClick={reindex} disabled={busy} className="inline-flex items-center gap-1 rounded border border-gray-300 bg-white px-2 py-1 text-gray-700">
            <RefreshCw className="h-3 w-3" aria-hidden /> Re-read
          </button>
        </div>
        <p className="mt-1 break-all">
          Folder on the server: <code>{p.folder}</code>
          {!p.exists && <span className="text-amber-700"> (does not exist yet: create it and copy the files in)</span>}
        </p>
        <p className="mt-1">Supported: .pdf, .docx, .txt, .md. New or changed files are picked up automatically.</p>
        {p.files.length > 0 && <p className="mt-1">{p.files.join(" · ")}</p>}
        {Object.entries(p.errors).map(([f, e]) => (
          <p key={f} className="mt-1 text-red-600">
            {f}: {e}
          </p>
        ))}
      </div>
    </div>
  );
}
