import type { Metadata } from "next";
import { headers } from "next/headers";
import { Space_Grotesk, Inter, Lexend_Deca } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const display = Space_Grotesk({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});
const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});
const logo = Lexend_Deca({
  subsets: ["latin"],
  weight: ["700"],
  variable: "--font-logo",
  display: "swap",
});

export const metadata: Metadata = {
  title: "AutoAccounting",
  description: "Drop client documents; get sorted records, BIR returns and books of accounts.",
};

export default async function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  // Nonce minted per-request in middleware.ts; forwarded to next-themes so its
  // pre-hydration theme script is allow-listed under the nonce CSP.
  const nonce = (await headers()).get("x-nonce") ?? undefined;
  return (
    <html lang="en" className={`${display.variable} ${sans.variable} ${logo.variable}`} suppressHydrationWarning>
      <body className="antialiased" suppressHydrationWarning>
        <Providers nonce={nonce}>{children}</Providers>
      </body>
    </html>
  );
}
