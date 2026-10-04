import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthContext";
import { ProfileProvider } from "./profile/ProfileContext";
import { ProtectedRoute } from "./components/ProtectedRoute";
import { Layout } from "./components/Layout";
import { Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { Analytics } from "./pages/Analytics";
import { Unknowns } from "./pages/Unknowns";
import { Employees } from "./pages/Employees";
import { Settings } from "./pages/Settings";
import { Reports } from "./pages/Reports";
import { Shifts } from "./pages/Shifts";
import { Muster } from "./pages/Muster";
import { Alerts } from "./pages/Alerts";
import { Sites } from "./pages/Sites";
import { ChangePassword } from "./pages/ChangePassword";
import { Payroll } from "./pages/Payroll";
import { Holidays } from "./pages/Holidays";
import { Admin } from "./pages/Admin";

export function App(): JSX.Element {
  return (
    <ProfileProvider>
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route path="/change-password" element={<ProtectedRoute><ChangePassword /></ProtectedRoute>} />
        <Route
          element={
            <ProtectedRoute>
              <Layout />
            </ProtectedRoute>
          }
        >
          <Route path="/" element={<Dashboard />} />
          <Route path="/analytics" element={<Analytics />} />
          <Route path="/unknowns" element={<Unknowns />} />
          <Route path="/employees" element={<Employees />} />
          <Route path="/settings" element={<ProtectedRoute need="admin"><Settings /></ProtectedRoute>} />
          <Route path="/admin" element={<ProtectedRoute need="admin"><Admin /></ProtectedRoute>} />
          <Route path="/payroll" element={<ProtectedRoute need="hr"><Payroll /></ProtectedRoute>} />
          <Route path="/holidays" element={<Holidays />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/shifts" element={<Shifts />} />
          <Route path="/muster" element={<Muster />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="/sites" element={<Sites />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </AuthProvider>
    </ProfileProvider>
  );
}
