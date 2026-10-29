import type { Metadata, Viewport } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Bozii — Autonomous AI Workforce",
    template: "%s · Bozii",
  },
  description:
    "Bozii is an open-source platform where you hire AI employees, delegate real digital work, and let them build the tools they are missing — in a sandbox, with tests, under your permission policy.",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#fafaf9",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}