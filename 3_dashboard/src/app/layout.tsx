import type { Metadata } from 'next';
import './globals.css';
import TopNav from '@/components/TopNav';

export const metadata: Metadata = {
  title: '비급여 수가 전략 대시보드',
  description: '빅5 병원 비급여 항목 모니터링 및 AI 클러스터링 관리 시스템',
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ko">
      <head>
        <link
          href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard/dist/web/variable/pretendardvariable-dynamic-subset.css"
          rel="stylesheet"
        />
      </head>
      <body>
        <TopNav />
        <main className="main-content">{children}</main>
      </body>
    </html>
  );
}
