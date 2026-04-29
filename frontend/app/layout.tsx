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
      <body>
        <Nav />
        <main className="max-w-6xl mx-auto px-6 py-6">{children}</main>
      </body>
    </html>
  );
}
