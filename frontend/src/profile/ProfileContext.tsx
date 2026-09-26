import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getProfile } from "../api/client";
import type { ClientProfile } from "../api/types";
import { DEFAULT_PROFILE } from "./defaults";

// The vendor-locked client profile (backend/app/services/client_profile.py):
// sector theme + wording ("Employee" / "Student" / "Staff") + departments.
// Read-only in the app -- it is set once with backend/scripts/setup_client.py.

const ProfileContext = createContext<ClientProfile>(DEFAULT_PROFILE);

export function ProfileProvider({ children }: { children: ReactNode }): JSX.Element {
  const [profile, setProfile] = useState<ClientProfile>(DEFAULT_PROFILE);

  useEffect(() => {
    let cancelled = false;
    getProfile()
      .then((p) => {
        if (!cancelled) setProfile({ ...DEFAULT_PROFILE, ...p });
      })
      .catch(() => {
        /* offline / old backend: keep the neutral default */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    document.documentElement.dataset.sector = profile.org_type;
    document.title = profile.configured ? `${profile.org_name} · Attendance` : "Face Attendance";
  }, [profile]);

  return <ProfileContext.Provider value={profile}>{children}</ProfileContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useProfile(): ClientProfile {
  return useContext(ProfileContext);
}
