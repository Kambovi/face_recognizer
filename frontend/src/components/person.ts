import { useEffect, useState } from "react";
import { listCameras } from "../api/client";
import type { CameraOut } from "../api/types";

// Non-component helpers for PersonFields (kept separate for react-refresh).

export interface PersonValues {
  name: string;
  emp_code: string;
  department: string;
  designation: string;
  home_kiosk_id: string;
}

export const EMPTY_PERSON: PersonValues = { name: "", emp_code: "", department: "", designation: "", home_kiosk_id: "" };

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
} {
  return {
    department: v.department.trim() || null,
    designation: v.designation.trim() || null,
    home_kiosk_id: v.home_kiosk_id || null,
  };
}
