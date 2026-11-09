"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useEffect, useState } from "react";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(() => new QueryClient());

  // Client-side keep-alive to keep the cloud backend warm and prevent cold-starts
  useEffect(() => {
    const apiBase = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000/api/v1";
    const pingBackend = () => {
      fetch(`${apiBase}/system/health`, { method: "GET", mode: "cors" }).catch(() => {});
    };

    // Initial wake-up ping
    pingBackend();

    // Repeat ping every 7 minutes while user is on the site
    const interval = setInterval(pingBackend, 7 * 60 * 1000);
    return () => clearInterval(interval);
  }, []);

  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
