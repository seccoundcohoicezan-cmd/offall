import { create } from "zustand";
import { persist } from "zustand/middleware";

interface UiState {
  theme: "dark" | "light";
  navOpen: boolean;
  draftModel: string;
  setTheme: (t: "dark" | "light") => void;
  setNavOpen: (open: boolean) => void;
  setDraftModel: (m: string) => void;
}

/** Only harmless UI preferences live in localStorage; never tokens. */
export const useUi = create<UiState>()(
  persist(
    (set) => ({
      theme: "dark",
      navOpen: false,
      draftModel: "auto",
      setTheme: (theme) => set({ theme }),
      setNavOpen: (navOpen) => set({ navOpen }),
      setDraftModel: (draftModel) => set({ draftModel }),
    }),
    { name: "offall-ui", partialize: (s) => ({ theme: s.theme, draftModel: s.draftModel }) },
  ),
);
