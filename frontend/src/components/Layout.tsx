import { useEffect, useRef, useState } from "react";
import { Link, NavLink, Outlet, useLocation } from "react-router-dom";
import clsx from "clsx";
import { Building2, ChevronDown, GraduationCap, Hospital, LogOut, Menu, Siren, X, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { AlertBell } from "./alerts/AlertBell";
import { ChatWidget } from "./chat/ChatWidget";
import { useProfile } from "../profile/ProfileContext";
import type { OrgType } from "../api/types";

const SECTOR_ICON: Record<OrgType, LucideIcon> = {
  business: Building2,
  school: GraduationCap,
  hospital: Hospital,
};

// One header for every screen size:
//   lg+      logo | nav | bell, Emergency, account menu -- all on one row
//   < lg     logo | bell, Emergency, menu button -> full-width menu panel
// (Before 2026-09-26 the header wrapped onto two rows even on a laptop and
// took a third of a phone screen.)
export function Layout(): JSX.Element {
  const { user, signOut } = useAuth();
  const profile = useProfile();
  const SectorIcon = SECTOR_ICON[profile.org_type] ?? Building2;
  const [menuOpen, setMenuOpen] = useState(false);
  const location = useLocation();

  useEffect(() => setMenuOpen(false), [location.pathname]);

  const navItems = [
    { to: "/", label: "Dashboard" },
    { to: "/analytics", label: "Analytics" },
    { to: "/employees", label: profile.person_label_plural },
    { to: "/unknowns", label: "Unknown faces" },
    { to: "/reports", label: "Reports" },
    { to: "/shifts", label: "Shifts" },
    { to: "/sites", label: "Sites" },
    { to: "/settings", label: "Settings", adminOnly: true },
  ].filter((item) => !item.adminOnly || user?.role === "admin");

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-gray-200 bg-white/95 backdrop-blur print:hidden">
        <div className="mx-auto flex max-w-7xl items-center gap-3 px-4 py-2.5">
          <Link to="/" className="flex min-w-0 shrink-0 items-center gap-2">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-brand-600 text-white">
              <SectorIcon className="h-4 w-4" aria-hidden />
            </span>
            <span className="min-w-0 leading-tight">
              <span className="block max-w-[11rem] truncate text-sm font-semibold text-gray-900 sm:max-w-none">{profile.org_name}</span>
              <span className="block text-[11px] text-gray-500">Face attendance</span>
            </span>
          </Link>

          <nav className="ml-4 hidden flex-1 items-center gap-0.5 lg:flex">
            {navItems.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.to === "/"}
                className={({ isActive }) =>
                  clsx(
                    "whitespace-nowrap rounded-md px-2.5 py-2 text-sm font-medium transition-colors",
                    isActive ? "bg-brand-50 text-brand-700" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
                  )
                }
              >
                {item.label}
              </NavLink>
            ))}
          </nav>

          <div className="ml-auto flex items-center gap-1.5">
            <AlertBell />
            <Link
              to="/muster"
              className="inline-flex items-center gap-1.5 rounded-md bg-red-600 px-2.5 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-red-700"
              title="Emergency muster: who is inside right now"
            >
              <Siren className="h-4 w-4" aria-hidden />
              <span className="hidden sm:inline">Emergency</span>
            </Link>
            <div className="hidden lg:block">
              <AccountMenu email={user?.email ?? ""} role={user?.role ?? ""} onSignOut={signOut} />
            </div>
            <button
              onClick={() => setMenuOpen((v) => !v)}
              className="rounded-md p-2 text-gray-600 hover:bg-gray-100 lg:hidden"
              aria-label={menuOpen ? "Close menu" : "Open menu"}
              aria-expanded={menuOpen}
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>

        {menuOpen && (
          <div className="border-t border-gray-100 bg-white px-4 pb-4 pt-2 lg:hidden">
            <nav className="grid grid-cols-2 gap-1">
              {navItems.map((item) => (
                <NavLink
                  key={item.to}
                  to={item.to}
                  end={item.to === "/"}
                  className={({ isActive }) =>
                    clsx(
                      "rounded-md px-3 py-2.5 text-sm font-medium",
                      isActive ? "bg-brand-50 text-brand-700" : "text-gray-700 hover:bg-gray-100",
                    )
                  }
                >
                  {item.label}
                </NavLink>
              ))}
            </nav>
            <div className="mt-3 flex items-center justify-between border-t border-gray-100 pt-3">
              <span className="truncate text-sm text-gray-500">
                {user?.email} <span className="text-gray-400">({user?.role})</span>
              </span>
              <button onClick={signOut} className="inline-flex items-center gap-1 rounded-md border border-gray-300 px-3 py-1.5 text-sm text-gray-700">
                <LogOut className="h-4 w-4" aria-hidden /> Sign out
              </button>
            </div>
          </div>
        )}
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
      <ChatWidget />
    </div>
  );
}

function AccountMenu({ email, role, onSignOut }: { email: string; role: string; onSignOut: () => void }): JSX.Element {
  const [open, setOpen] = useState(false);
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent): void => {
      if (box.current && !box.current.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, [open]);
  const initials = email.slice(0, 2).toUpperCase();
  return (
    <div className="relative" ref={box}>
      <button
        onClick={() => setOpen((v) => !v)}
        className="flex items-center gap-1 rounded-md p-1 hover:bg-gray-100"
        aria-label="Account menu"
        aria-expanded={open}
      >
        <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gray-200 text-[11px] font-semibold text-gray-700">{initials}</span>
        <ChevronDown className="h-4 w-4 text-gray-400" aria-hidden />
      </button>
      {open && (
        <div className="absolute right-0 z-40 mt-2 w-60 rounded-xl border border-gray-200 bg-white p-2 shadow-xl">
          <p className="truncate px-2 pt-1 text-sm font-medium text-gray-900">{email}</p>
          <p className="px-2 pb-2 text-xs text-gray-500">Role: {role}</p>
          <button onClick={onSignOut} className="flex w-full items-center gap-2 rounded-md px-2 py-2 text-sm text-gray-700 hover:bg-gray-100">
            <LogOut className="h-4 w-4" aria-hidden /> Sign out
          </button>
        </div>
      )}
    </div>
  );
}
