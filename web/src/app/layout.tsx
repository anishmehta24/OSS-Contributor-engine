import type { Metadata } from "next";
import { Inter, Fraunces, JetBrains_Mono } from "next/font/google";
import { ThemeProvider } from "@/components/theme-provider";
import { Toaster } from "@/components/ui/sonner";
import "./globals.css";

// Body — Inter (clean, highly readable).
const inter = Inter({
  variable: "--font-inter",
  subsets: ["latin"],
});

// Headings / display — Fraunces (a classic old-style serif with modern
// optical sizing). Gives the whole product an editorial, timeless feel.
const fraunces = Fraunces({
  variable: "--font-fraunces",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  style: ["normal", "italic"],
});

// Monospace — JetBrains Mono (code, numbers, metadata).
const jetbrainsMono = JetBrains_Mono({
  variable: "--font-jetbrains-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "OSS Engine — Open-source issues that match your skills",
    template: "%s · OSS Engine",
  },
  description:
    "Multi-agent platform that profiles your GitHub history, hunts matching OSS issues, investigates them end-to-end, and drafts pitch comments.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // `suppressHydrationWarning` is recommended by next-themes because the
  // theme class is applied client-side before React rehydrates.
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${inter.variable} ${fraunces.variable} ${jetbrainsMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-background font-sans">
        <ThemeProvider
          attribute="class"
          defaultTheme="light"
          enableSystem
          disableTransitionOnChange
        >
          {children}
          <Toaster richColors closeButton />
        </ThemeProvider>
      </body>
    </html>
  );
}
