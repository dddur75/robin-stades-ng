import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  metadataBase: new URL("https://robin-stades-shadow-cockpit.openai.site"),
  title: {
    default: "Robin des Stades — Explorer avant de conclure",
    template: "%s · Robin des Stades",
  },
  description:
    "Le cockpit scientifique de Robin observe le football avec des preuves datées, sans pari réel ni promesse de gain.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "Robin des Stades · Cockpit scientifique",
    description:
      "Observer les matchs, les résultats et les recherches de Robin sans réécrire le passé.",
    images: [
      {
        alt: "Une constellation arborescente d’hypothèses football dans un stade nocturne",
        height: 910,
        url: "/og.png",
        width: 1728,
      },
    ],
    locale: "fr_FR",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Robin des Stades · Cockpit scientifique",
    description:
      "Une observation football transparente, sans pari réel ni promesse de gain.",
    images: ["/og.png"],
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="fr-FR">
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased`}
      >
        {children}
      </body>
    </html>
  );
}
