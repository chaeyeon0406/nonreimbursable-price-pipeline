'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import {
    Search,
    MessageSquareWarning,
    BarChart3,
    DatabaseZap,
} from 'lucide-react';

const navItems = [
    { href: '/', label: '수가 비교 탐색기', icon: Search },
    { href: '/hira', label: 'HIRA API 데이터', icon: DatabaseZap },
    { href: '/feedback', label: '피드백 & 오류수정', icon: MessageSquareWarning },
    { href: '/reports', label: '분석 리포트', icon: BarChart3 },
];

export default function TopNav() {
    const pathname = usePathname();

    return (
        <header className="top-nav">
            <div className="top-nav-logo">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <span style={{ fontSize: 20 }}>💊</span>
                    <div>
                        <h1>비급여 수가 전략</h1>
                        <p>Non-Coverage Pricing Monitor</p>
                    </div>
                </div>
            </div>
            <nav className="top-nav-menu">
                {navItems.map((item) => {
                    const isActive = item.href === '/' ? pathname === '/' : pathname.startsWith(item.href);
                    const Icon = item.icon;
                    return (
                        <Link
                            key={item.href}
                            href={item.href}
                            className={`top-nav-link ${isActive ? 'active' : ''}`}
                        >
                            <Icon className="icon" />
                            <span>{item.label}</span>
                        </Link>
                    );
                })}
            </nav>
            <div className="top-nav-right">
                <div className="user-profile">
                    <div className="avatar">A</div>
                    <span>관리자</span>
                </div>
            </div>
        </header>
    );
}
