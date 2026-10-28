import type { Metadata, Viewport } from "next";
import { Plus_Jakarta_Sans } from "next/font/google";
import "./globals.css";
import { Providers } from "@/components/Providers";

const jakarta = Plus_Jakarta_Sans({ subsets: ["latin"], variable: "--font-jakarta" });

export const metadata: Metadata = {
  title: "OFALL — AI Gateway & Agent Multi-Provider",
  description: "Satu chat, banyak AI. Rotasi API key otomatis, hemat token, tetap jalan saat offline.",
  manifest: "/manifest.webmanifest",
  icons: { icon: "/icon-192.png", apple: "/icon-192.png" },
};

export const viewport: Viewport = { themeColor: "#070a1a", width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="id" className="dark" suppressHydrationWarning>
      <body className={`${jakarta.variable} font-sans antialiased`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
