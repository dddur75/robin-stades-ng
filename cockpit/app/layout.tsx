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
    default: "Robin des Stades — Observer avant de conclure",
    template: "%s · Robin des Stades",
  },
  description:
    "Robin observe les matchs, vérifie les données pré-match et publie ses résultats sans pari réel ni promesse de gain.",
  icons: {
    icon: "/favicon.svg",
    shortcut: "/favicon.svg",
  },
  openGraph: {
    title: "Robin des Stades — Observer avant de conclure",
    description:
      "Neuf rencontres suivies, des preuves datées et une recherche football transparente.",
    images: ["/og.png"],
    locale: "fr_FR",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "Robin des Stades — Observer avant de conclure",
    description: "L’observatoire football transparent, sans pari réel.",
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
