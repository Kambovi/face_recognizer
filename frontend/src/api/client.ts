import axios, { type AxiosError, type AxiosInstance } from "axios";
import type {
  AnalyticsOverview,
  AnalyticsPeriod,
  CameraOut,
  ClientProfile,
  AnalyticsSummaryResponse,
  AttendanceEventListResponse,
  AttendanceEventOut,
  ConsentCreate,
  ConsentOut,
  DashboardTodayResponse,
  EmployeeCreate,
  EmployeeListResponse,
  EmployeeOut,
  EmployeeUpdate,
  EnrollResponse,
  FaceTemplateOut,
  HealthResponse,
  LinkRequest,
  LoginRequest,
  LoginResponse,
  ManualEventCreate,
  ManualOverrideRequest,
  PromoteRequest,
  PromoteResponse,
  ReassignRequest,
  SettingsResponse,
  SettingsUpdateRequest,
  ShiftOut,
  SplitRequest,
  SplitResponse,
  UnknownIdentityOut,
  UnknownListResponse,
  UnknownUpdateRequest,
} from "./types";

// Vite exposes build-time env vars via import.meta.env; falls back to the
// same-origin nginx proxy path in production (see frontend/nginx.conf /
// docker-compose.yml's VITE_API_BASE_URL build arg).
export const API_BASE_URL: string = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? "http://localhost:8000";

const TOKEN_STORAGE_KEY = "face_attendance_token";

export function getStoredToken(): string | null {
  try {
    return window.localStorage.getItem(TOKEN_STORAGE_KEY);
  } catch {
    return null;
  }
}

export function setStoredToken(token: string | null): void {
  try {
    if (token) {
      window.localStorage.setItem(TOKEN_STORAGE_KEY, token);
    } else {
      window.localStorage.removeItem(TOKEN_STORAGE_KEY);
    }
  } catch {
    // localStorage unavailable (private browsing, etc.) -- the session
    // simply won't persist across reloads, which is an acceptable
    // degradation rather than a crash.
  }
}

const http: AxiosInstance = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  timeout: 15000,
});

http.interceptors.request.use((config) => {
  const token = getStoredToken();
  if (token) {
    config.headers = config.headers ?? {};
    config.headers.Authorization = `Bearer ${token}`;
  }
  return config;
});

export interface ApiError {
  status: number | null;
  code: string;
  detail: string;
}

export function toApiError(error: unknown): ApiError {
  const axiosError = error as AxiosError<{ detail?: string; code?: string }>;
  if (axiosError.isAxiosError) {
    const body = axiosError.response?.data;
    return {
      status: axiosError.response?.status ?? null,
      code: body?.code ?? "network_error",
      detail: body?.detail ?? axiosError.message,
    };
  }
  return { status: null, code: "unknown_error", detail: String(error) };
}

let onUnauthorized: (() => void) | null = null;
export function setUnauthorizedHandler(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

http.interceptors.response.use(
  (response) => response,
  (error: AxiosError) => {
    if (error.response?.status === 401) {
      onUnauthorized?.();
    }
    return Promise.reject(error);
  },
);

// -- auth -----------------------------------------------------------------------

export async function login(payload: LoginRequest): Promise<LoginResponse> {
  const { data } = await http.post<LoginResponse>("/auth/login", payload);
  return data;
}

// -- dashboard --------------------------------------------------------------

export async function getDashboardToday(): Promise<DashboardTodayResponse> {
  const { data } = await http.get<DashboardTodayResponse>("/dashboard/today");
  return data;
}

export interface DashboardParams {
  /** Inclusive local (Asia/Kolkata) dates, "YYYY-MM-DD". Max 366 days. */
  date_from: string;
  date_to: string;
}

export async function getDashboard(params: DashboardParams): Promise<DashboardTodayResponse> {
  const { data } = await http.get<DashboardTodayResponse>("/dashboard", { params });
  return data;
}

// -- attendance ---------------------------------------------------------------

export interface ListEventsParams {
  date_from?: string;
  date_to?: string;
  subject_type?: string;
  reject_reason?: string;
  page?: number;
  page_size?: number;
}

export async function listEvents(params: ListEventsParams = {}): Promise<AttendanceEventListResponse> {
  const { data } = await http.get<AttendanceEventListResponse>("/attendance/events", { params });
  return data;
}

export async function manualOverrideEvent(eventId: string, payload: ManualOverrideRequest): Promise<AttendanceEventOut> {
  const { data } = await http.patch<AttendanceEventOut>(`/attendance/events/${eventId}`, payload);
  return data;
}

export async function reassignEvent(eventId: string, payload: ReassignRequest): Promise<AttendanceEventOut> {
  const { data } = await http.patch<AttendanceEventOut>(`/attendance/events/${eventId}/reassign`, payload);
  return data;
}

// -- unknowns -----------------------------------------------------------------

export interface ListUnknownsParams {
  status?: string;
  sort?: string;
  page?: number;
  page_size?: number;
}

export async function listUnknowns(params: ListUnknownsParams = {}): Promise<UnknownListResponse> {
  const { data } = await http.get<UnknownListResponse>("/unknowns", { params });
  return data;
}

export async function updateUnknown(unknownId: string, payload: UnknownUpdateRequest): Promise<UnknownIdentityOut> {
  const { data } = await http.patch<UnknownIdentityOut>(`/unknowns/${unknownId}`, payload);
  return data;
}

export async function deleteUnknown(unknownId: string): Promise<void> {
  await http.delete(`/unknowns/${unknownId}`);
}

export async function linkUnknown(unknownId: string, payload: LinkRequest): Promise<UnknownIdentityOut> {
  const { data } = await http.post<UnknownIdentityOut>(`/unknowns/${unknownId}/link`, payload);
  return data;
}

export async function promoteUnknown(unknownId: string, payload: PromoteRequest): Promise<PromoteResponse> {
  const { data } = await http.post<PromoteResponse>(`/unknowns/${unknownId}/promote`, payload);
  return data;
}

export async function splitUnknown(unknownId: string, payload: SplitRequest): Promise<SplitResponse> {
  const { data } = await http.post<SplitResponse>(`/unknowns/${unknownId}/split`, payload);
  return data;
}

export async function listUnknownTemplates(unknownId: string): Promise<FaceTemplateOut[]> {
  const { data } = await http.get<FaceTemplateOut[]>(`/unknowns/${unknownId}/templates`);
  return data;
}

// -- employees ------------------------------------------------------------------

export interface ListEmployeesParams {
  department?: string;
  is_active?: boolean;
  page?: number;
  page_size?: number;
}

export async function listEmployees(params: ListEmployeesParams = {}): Promise<EmployeeListResponse> {
  const { data } = await http.get<EmployeeListResponse>("/employees", { params });
  return data;
}

export async function createEmployee(payload: EmployeeCreate): Promise<EmployeeOut> {
  const { data } = await http.post<EmployeeOut>("/employees", payload);
  return data;
}

export async function updateEmployee(employeeId: string, payload: EmployeeUpdate): Promise<EmployeeOut> {
  const { data } = await http.patch<EmployeeOut>(`/employees/${employeeId}`, payload);
  return data;
}

export async function deleteEmployee(employeeId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}`);
}

export async function grantConsent(employeeId: string, payload: ConsentCreate): Promise<ConsentOut> {
  const { data } = await http.post<ConsentOut>(`/employees/${employeeId}/consent`, payload);
  return data;
}

export async function revokeConsent(employeeId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}/consent`);
}

export async function enrollEmployee(employeeId: string, files: File[]): Promise<EnrollResponse> {
  const form = new FormData();
  for (const file of files) {
    form.append("files", file);
  }
  const { data } = await http.post<EnrollResponse>(`/employees/${employeeId}/enroll`, form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function listTemplates(employeeId: string): Promise<FaceTemplateOut[]> {
  const { data } = await http.get<FaceTemplateOut[]>(`/employees/${employeeId}/templates`);
  return data;
}

export async function deleteTemplate(employeeId: string, templateId: string): Promise<void> {
  await http.delete(`/employees/${employeeId}/templates/${templateId}`);
}

// -- shifts ---------------------------------------------------------------------

export async function listShifts(): Promise<ShiftOut[]> {
  const { data } = await http.get<ShiftOut[]>("/shifts");
  return data;
}

export interface ShiftCreate {
  name: string;
  in_time: string;
  out_time: string;
  grace_minutes: number;
  is_default: boolean;
}

export async function createShift(payload: ShiftCreate): Promise<ShiftOut> {
  const { data } = await http.post<ShiftOut>("/shifts", payload);
  return data;
}

// -- analytics ------------------------------------------------------------------

export interface AnalyticsSummaryParams {
  period: AnalyticsPeriod;
  date_from?: string;
  date_to?: string;
  subject_id?: string;
  include_unknowns?: boolean;
}

export async function getAnalyticsSummary(params: AnalyticsSummaryParams): Promise<AnalyticsSummaryResponse> {
  const { data } = await http.get<AnalyticsSummaryResponse>("/analytics/summary", { params });
  return data;
}

/** CSV export needs the login token, which a plain <a href> can't send --
 *  fetch it through the authenticated client and save it as a file. */
export async function downloadAnalyticsCsv(params: AnalyticsSummaryParams): Promise<void> {
  const res = await http.get<Blob>("/analytics/export.csv", { params, responseType: "blob" });
  const url = URL.createObjectURL(res.data);
  const a = document.createElement("a");
  a.href = url;
  a.download = `attendance_${params.date_from ?? params.period}_${params.date_to ?? ""}.csv`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

export function analyticsExportCsvUrl(params: AnalyticsSummaryParams): string {
  const search = new URLSearchParams();
  search.set("period", params.period);
  if (params.date_from) search.set("date_from", params.date_from);
  if (params.date_to) search.set("date_to", params.date_to);
  if (params.subject_id) search.set("subject_id", params.subject_id);
  if (params.include_unknowns) search.set("include_unknowns", "true");
  return `${API_BASE_URL}/api/v1/analytics/export.csv?${search.toString()}`;
}

// -- settings -------------------------------------------------------------------

export async function getSettings(): Promise<SettingsResponse> {
  const { data } = await http.get<SettingsResponse>("/settings");
  return data;
}

export async function updateSettings(payload: SettingsUpdateRequest): Promise<SettingsResponse> {
  const { data } = await http.patch<SettingsResponse>("/settings", payload);
  return data;
}

// -- health -----------------------------------------------------------------------

export async function getHealth(): Promise<HealthResponse> {
  const { data } = await http.get<HealthResponse>("/health");
  return data;
}

// -- media (crop images) -------------------------------------------------------

export function mediaUrl(path: string | null): string | null {
  if (!path) return null;
  return path.startsWith("http") ? path : `${API_BASE_URL}${path}`;
}

export default http;

// -- manual attendance entry ----------------------------------------------------

export async function createManualEvent(payload: ManualEventCreate): Promise<AttendanceEventOut> {
  const { data } = await http.post<AttendanceEventOut>("/attendance/events/manual", payload);
  return data;
}

// -- client profile + cameras ------------------------------------------------------

export async function getProfile(): Promise<ClientProfile> {
  const { data } = await http.get<ClientProfile>("/profile");
  return data;
}

export async function listCameras(): Promise<CameraOut[]> {
  const { data } = await http.get<CameraOut[]>("/cameras");
  return data;
}

// -- analytics overview -------------------------------------------------------------

export async function getAnalyticsOverview(params: { date_from: string; date_to: string }): Promise<AnalyticsOverview> {
  const { data } = await http.get<AnalyticsOverview>("/analytics/overview", { params });
  return data;
}
