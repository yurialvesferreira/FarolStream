import type { Metadata } from 'next';
import './globals.css';

export const metadata: Metadata = {
  title: 'FarolStream — Painel de Operações',
  description:
    'Dashboard em tempo real via Server-Sent Events: logs, alertas e trades.',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="pt-BR">
      <body>{children}</body>
    </html>
  );
}
