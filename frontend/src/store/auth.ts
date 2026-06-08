import { create } from "zustand";
import type { User } from "@/lib/api";

/**
 * Client-side auth state.
 *
 * SECURITY: JWTs are NEVER stored here or in any browser-accessible storage
 * (localStorage/sessionStorage). Access + refresh tokens live exclusively in
 * httpOnly cookies (`ss_access` / `ss_refresh`) set by the BFF route handlers
 * under src/app/api/* — see src/app/api/auth/login/route.ts. Browser JS cannot
 * read those cookies, so an XSS payload cannot exfiltrate the session.
 *
 * This store therefore holds only the non-sensitive `user` profile, in memory
 * only (no persistence). It is safe to hydrate from `/api/auth/me` on load.
 */
interface AuthState {
  user: User | null;
  setUser: (user: User | null) => void;
  clear: () => void;
}

export const useAuthStore = create<AuthState>()((set) => ({
  user: null,
  setUser: (user) => set({ user }),
  clear: () => set({ user: null }),
}));
