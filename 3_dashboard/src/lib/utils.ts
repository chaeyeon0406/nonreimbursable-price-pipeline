import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
    return twMerge(clsx(inputs));
}

export function formatCurrency(value: number): string {
    if (value >= 100000000) {
        return `${(value / 100000000).toFixed(1)}억`;
    }
    if (value >= 10000) {
        return `${Math.round(value / 10000).toLocaleString()}만`;
    }
    return value.toLocaleString() + '원';
}

export function formatNumber(value: number): string {
    return value.toLocaleString();
}

export function getPriceGapPercent(min: number, max: number): number {
    if (min === 0) return 0;
    return Math.round(((max - min) / min) * 100);
}
