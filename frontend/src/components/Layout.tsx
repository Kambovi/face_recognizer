import { Link, NavLink, Outlet } from "react-router-dom";
import clsx from "clsx";
import { Building2, GraduationCap, Hospital, Siren, type LucideIcon } from "lucide-react";
import { useAuth } from "../auth/AuthContext";
import { useProfile } from "../profile/ProfileContext";
import type { OrgType } from "../api/types";

const SECTOR_ICON: Record<OrgType, LucideIcon> = {
  business: Building2,
  school: GraduationCap,
  hospital: Hospital,
};

export function Layout(): JSX.Element {
  const { user, signOut } = useAuth();
  const profile = useProfile();
  const SectorIcon = SECTOR_ICON[profile.org_type] ?? Building2;

  const navItems: { to: string; label: string; adminOnly?: boolean }[] = [
    { to: "/", label: "Dashboard" },
    { to: "/analytics", label: "Analytics" },
    { to: "/employees", label: profile.person_label_plural },
    { to: "/unknowns", label: "Unknown faces" },
    { to: "/reports", label: "Reports" },
    { to: "/shifts", label: "Shifts" },
    { to: "/settings", label: "Settings", adminOnly: true },
  ];

  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-gray-200 bg-white print:hidden">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-4 py-3">
          <div className="flex flex-wrap items-center gap-6">
            <span className="flex items-center gap-2">
              <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-brand-600 text-white">
                <SectorIcon className="h-4 w-4" aria-hidden />
              </span>
              <span className="leading-tight">
                <span className="block text-sm font-semibold text-gray-900">{profile.org_name}</span>
                <span className="block text-[11px] text-gray-500">Face attendance</span>
              </span>
            </span>
            <nav className="flex flex-wrap gap-1">
              {navItems
                .filter((item) => !item.adminOnly || user?.role === "admin")
                .map((item) => (
                  <NavLink
                    key={item.to}
                    to={item.to}
                    end={item.to === "/"}
                    className={({ isActive }) =>
                      clsx(
                        "rounded-md px-3 py-2 text-sm font-medium transition-colors",
                        isActive ? "bg-brand-50 text-brand-700" : "text-gray-600 hover:bg-gray-100 hover:text-gray-900",
                      )
                    }
                  >
                    {item.label}
                  </NavLink>
                ))}
            </nav>
          </div>
          <div className="flex items-center gap-4">
            <Link
              to="/muster"
              className="inline-flex items-center gap-1.5 rounded-md bg-red-600 px-3 py-1.5 text-sm font-semibold text-white shadow-sm hover:bg-red-700"
              title="Emergency muster: who is inside right now"
            >
              <Siren className="h-4 w-4" aria-hidden /> Emergency
            </Link>
            <span className="text-sm text-gray-500">
              {user?.email} <span className="text-gray-400">({user?.role})</span>
            </span>
            <button
              onClick={signOut}
              className="rounded-md border border-gray-300 px-3 py-1.5 text-sm font-medium text-gray-700 hover:bg-gray-50"
            >
              Sign out
            </button>
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-7xl flex-1 px-4 py-6">
        <Outlet />
      </main>
    </div>
  );
}
