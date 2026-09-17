import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RAGX | Multimodal RAG",
  description: "واجهة ذكية للبحث والتحدث مع مستنداتك",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ar" dir="rtl">
      <body>{children}</body>
    </html>
  );
}
