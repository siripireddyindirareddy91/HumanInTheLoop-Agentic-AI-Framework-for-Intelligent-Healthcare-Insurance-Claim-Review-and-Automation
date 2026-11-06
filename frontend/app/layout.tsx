import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title: 'ClaimGuard AI | Intelligent claims. Human judgment.', description: 'Evidence-led healthcare insurance claim investigation with accountable human oversight.' };
export default function RootLayout({children}:Readonly<{children:React.ReactNode}>){return <html lang="en"><body>{children}</body></html>}
