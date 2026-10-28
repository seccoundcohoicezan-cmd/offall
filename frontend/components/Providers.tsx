"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState, type ReactNode } from "react";
import { Toaster } from "./ui/toast";
import { useUi } from "@/lib/store";

export function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: { queries: { staleTime: 10_000, refetchOnWindowFocus: true, retry: 1 } },
      }),
  );
  const theme = useUi((s) => s.theme);
  useEffect(() => {
    document.documentElement.classList.toggle("dark", theme === "dark");
  }, [theme]);
  useEffect(() => {
    if ("serviceWorker" in navigator && process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => undefined);
    }
  }, []);
  return (
    <QueryClientProvider client={client}>
      {children}
      <Toaster />
    </QueryClientProvider>
  );
}
