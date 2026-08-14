import type { Metadata } from "next";
import { Open_Sans, Poppins } from "next/font/google";

import "./globals.css";
import { AuthGuard } from "@/components/auth-guard";
import { BackgroundDecor } from "@/components/background-decor";
import { Navbar } from "@/components/navbar";
import { Providers } from "@/components/providers";

const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
});

const openSans = Open_Sans({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  variable: "--font-open-sans",
  display: "swap",
});

export const metadata: Metadata = {
  title: "TalentFinder — Candidate Search",
  description:
    "Enter hiring requirements and get ranked, scored candidate matches automatically.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${poppins.variable} ${openSans.variable}`}
    >
      <body>
        <Providers>
          <BackgroundDecor />
          <Navbar />
          <main className="mx-auto max-w-6xl px-4 pb-20 pt-28">
            <AuthGuard>{children}</AuthGuard>
          </main>
        </Providers>
      </body>
    </html>
  );
}
