import type { UserRole } from "@/types";

/** Where each role lands after sign-in. */
export function roleHome(role?: UserRole | string): string {
  switch (role) {
    case "admin":
      return "/admin";
    case "enterprise":
    case "manager":
    case "employee":
      return "/accounting";
    case "unverified":
      return "/pending";
    default:
      return "/login";
  }
}

/** The static marketing page (frontend/public/index.html, served by a rewrite). */
export const HOMEPAGE = "/";

export const PUBLIC_ROUTES = ["/", "/login"];

const FIRM_ROLES: UserRole[] = ["admin", "enterprise", "manager", "employee"];

/** Route prefixes each role may open. */
export function canAccess(role: UserRole | undefined, pathname: string): boolean {
  if (PUBLIC_ROUTES.includes(pathname)) return true;
  if (!role) return false;
  if (pathname.startsWith("/admin")) return role === "admin";
  if (pathname.startsWith("/team")) return role === "admin" || role === "enterprise" || role === "manager";
  if (pathname.startsWith("/accounting")) return FIRM_ROLES.includes(role);
  if (pathname.startsWith("/pending")) return role === "unverified";
  return false;
}

export function roleLabel(role?: UserRole): string {
  switch (role) {
    case "admin": return "Platform admin";
    case "enterprise": return "Firm owner";
    case "manager": return "Manager";
    case "employee": return "Employee";
    default: return "Unverified";
  }
}
