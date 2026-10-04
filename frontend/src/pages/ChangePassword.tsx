import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";
import type { ApiError } from "../api/client";
import { useProfile } from "../profile/ProfileContext";

const field = "w-full rounded-md border border-gray-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none focus:ring-1 focus:ring-brand-500";

/** Shown after login with a temporary password (and from the account menu). */
export function ChangePassword(): JSX.Element {
  const { user, changePassword, signOut } = useAuth();
  const profile = useProfile();
  const navigate = useNavigate();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const forced = Boolean(user?.must_change_password);

  async function submit(e: FormEvent<HTMLFormElement>): Promise<void> {
    e.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError("The two new passwords don't match.");
      return;
    }
    setBusy(true);
    try {
      await changePassword(current, next);
      navigate("/", { replace: true });
    } catch (err) {
      setError((err as ApiError).detail || "Could not change the password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-[70vh] items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-xl border border-gray-200 bg-white p-8 shadow-sm">
        <div className="mb-4 h-1.5 w-12 rounded-full bg-brand-600" aria-hidden />
        <h1 className="mb-1 text-xl font-semibold text-gray-900">{forced ? "Set your own password" : "Change password"}</h1>
        <p className="mb-6 text-sm text-gray-500">
          {forced
            ? `You signed in to ${profile.org_name} with a temporary password. Choose your own to continue.`
            : "Other devices signed in with your account will be signed out."}
        </p>
        <form onSubmit={submit} className="space-y-4">
          <label className="block text-sm font-medium text-gray-700">
            {forced ? "Temporary password" : "Current password"}
            <input type="password" required autoComplete="current-password" value={current}
              onChange={(e) => setCurrent(e.target.value)} className={`${field} mt-1`} />
          </label>
          <label className="block text-sm font-medium text-gray-700">
            New password
            <input type="password" required minLength={10} autoComplete="new-password" value={next}
              onChange={(e) => setNext(e.target.value)} className={`${field} mt-1`} />
            <span className="mt-1 block text-xs font-normal text-gray-500">At least 10 characters, letters and numbers.</span>
          </label>
          <label className="block text-sm font-medium text-gray-700">
            Repeat new password
            <input type="password" required autoComplete="new-password" value={repeat}
              onChange={(e) => setRepeat(e.target.value)} className={`${field} mt-1`} />
          </label>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <button type="submit" disabled={busy}
            className="w-full rounded-md bg-brand-600 px-3 py-2 text-sm font-medium text-white hover:bg-brand-700 disabled:opacity-60">
            {busy ? "Saving..." : "Save password"}
          </button>
          {forced && (
            <button type="button" onClick={signOut} className="w-full text-center text-sm text-gray-500 hover:underline">
              Sign out
            </button>
          )}
        </form>
      </div>
    </div>
  );
}
