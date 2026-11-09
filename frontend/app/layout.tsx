import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "./providers";
import { ThemeProvider } from "@/lib/theme";

export const metadata: Metadata = {
  title: "SatQuery AI",
  description: "Ask your satellite data a question. SatQuery finds, understands, explains and proves the answer.",
  icons: {
    icon: "/logo/satquertlogo.png",
    apple: "/logo/satquertlogo.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    // Keep "dark" as SSR default to prevent flash; ThemeProvider hydrates & overrides on client
    <html lang="en" className="dark" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <ThemeProvider>
          <Providers>{children}</Providers>
        </ThemeProvider>
      </body>
    </html>
  );
}
