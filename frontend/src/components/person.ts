import { useEffect, useState } from "react";
import { listCameras, listContractorNames } from "../api/client";
import type { CameraOut } from "../api/types";

// Non-component helpers for PersonFields (kept separate for react-refresh).

export interface PersonValues {
  name: string;
  emp_code: string;
  department: string;
  designation: string;
  home_kiosk_id: string;
  /** undefined = not editable here (field hidden, value left unchanged). */
  contractor?: string;
  /** Monthly salary in ₹ as typed; undefined = field hidden (not admin / not this form). */
  monthly_salary?: string;
}

export const EMPTY_PERSON: PersonValues = {
  name: "",
  emp_code: "",
  department: "",
  designation: "",
  home_kiosk_id: "",
  contractor: "",
};

export function useContractorNames(): string[] {
  const [names, setNames] = useState<string[]>([]);
  useEffect(() => {
    listContractorNames()
      .then(setNames)
      .catch(() => setNames([]));
  }, []);
  return names;
}

export function useCameras(): CameraOut[] {
  const [cameras, setCameras] = useState<CameraOut[]>([]);
  useEffect(() => {
    listCameras()
      .then(setCameras)
      .catch(() => setCameras([]));
  }, []);
  return cameras;
}

export function personPayload(v: PersonValues): {
  department: string | null;
  designation: string | null;
  home_kiosk_id: string | null;
  contractor?: string | null;
  monthly_salary?: number | null;
} {
  return {
    department: v.department.trim() || null,
    designation: v.designation.trim() || null,
    home_kiosk_id: v.home_kiosk_id || null,
    ...(v.contractor === undefined ? {} : { contractor: v.contractor.trim() || null }),
    ...(v.monthly_salary === undefined ? {} : { monthly_salary: parseSalary(v.monthly_salary) }),
  };
}

function parseSalary(v: string): number | null {
  const n = Number(v.replace(/[,₹\s]/g, ""));
  return v.trim() && Number.isFinite(n) && n >= 0 ? n : null;
}
