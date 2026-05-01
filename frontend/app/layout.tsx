import "./globals.css";
import type { Metadata } from "next";
import { Nav } from "../components/Nav";

export const metadata: Metadata = {
  title: "Insights Collect",
  description: "Multi-agent expert-viewpoint collection & deep-analysis platform",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body className="bg-parchment text-ink">
        <Nav />
        <main className="mx-auto max-w-grid px-lg py-xl">{children}</main>
      </body>
    </html>
  );
}
