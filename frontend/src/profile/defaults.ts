import type { ClientProfile } from "../api/types";

export const DEFAULT_PROFILE: ClientProfile = {
  configured: false,
  org_type: "business",
  org_name: "Face Attendance",
  departments: [],
  max_enrolled_per_camera: 200,
  person_label: "Employee",
  person_label_plural: "Employees",
  id_label: "Emp ID",
  department_label: "Department",
  department_label_plural: "Departments",
  designation_label: "Designation",
};

