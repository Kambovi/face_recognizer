import type { ReactElement } from "react";
import { Navigate, useLocation } from "react-router-dom";
import { useAuth } from "../auth/AuthContext";

export function ProtectedRoute({ children, need }: { children: ReactElement; need?: "admin" | "hr" }): ReactElement {
  const { user, isAdmin, isHr } = useAuth();
  const location = useLocation();

  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }
  if (user.must_change_password && location.pathname !== "/change-password") {
    return <Navigate to="/change-password" replace />;
  }
  if ((need === "admin" && !isAdmin) || (need === "hr" && !isHr)) {
    return <Navigate to="/" replace />;
  }
  return children;
}
