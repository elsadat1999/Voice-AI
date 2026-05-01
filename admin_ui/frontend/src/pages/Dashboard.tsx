import { useState, useEffect, useCallback } from 'react';
import {
    Phone, TrendingUp, Timer, Zap, Users, RefreshCw,
    Activity, BarChart3, PieChart as PieChartIcon, PhoneCall, CheckCircle2
} from 'lucide-react';
import {
    AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
    XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts';
import axios from 'axios';

// ─────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────
interface CallStats {
    total_calls: number;
    avg_duration_seconds: number;
    avg_latency_ms: number;
    providers: Record<string, number>;
    pipelines: Record<string, number>;
    contexts: Record<string, number>;
    calls_per_day: Array<{ date: string; count: number }>;
    top_callers: Array<{ number: string; count: number }>;
    outcomes: Record<string, number>;
    active_calls: number;
}

// ─────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────
const formatDuration = (s: number) => {
    if (!s) return '0s';
    if (s < 60) return `${Math.round(s)}s`;
    const m = Math.floor(s / 60);
    const sec = Math.round(s % 60);
    return `${m}m ${sec}s`;
};

const CHART_COLORS = [
    '#3b82f6', // blue-500
    '#64748b', // slate-500
    '#0ea5e9', // sky-500
    '#6366f1', // indigo-500
    '#14b8a6', // teal-500
    '#8b5cf6', // violet-500
];

const OUTCOME_COLORS: Record<string, string> = {
    completed: '#10b981', // emerald-500
    error: '#ef4444', // red-500
    transferred: '#3b82f6', // blue-500
    abandoned: '#f59e0b', // amber-500
};

// ─────────────────────────────────────────────
// KPI card
// ─────────────────────────────────────────────
interface KpiCardProps {
    title: string;
    value: string | number;
    sub?: string;
    icon: React.ReactNode;
    accentBg: string;   // e.g. "bg-indigo-500/10"
    accentText: string; // e.g. "text-indigo-400"
    borderAccent?: string; // e.g. "border-indigo-500/30"
}

const KpiCard = ({ title, value, sub, icon, accentBg, accentText, borderAccent = '' }: KpiCardProps) => (
    <div className={`rounded-xl border ${borderAccent || 'border-border'} bg-card p-5 flex flex-col gap-3 shadow-sm hover:shadow-md transition-all duration-200 hover:-translate-y-0.5`}>
        <div className="flex items-start justify-between">
            <span className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{title}</span>
            <div className={`${accentBg} ${accentText} p-2 rounded-lg`}>{icon}</div>
        </div>
        <div>
            <div className={`text-3xl font-bold tracking-tight ${accentText}`}>{value}</div>
            {sub && <div className="text-xs text-muted-foreground mt-1.5">{sub}</div>}
        </div>
    </div>
);

// ─────────────────────────────────────────────
// Chart card wrapper
// ─────────────────────────────────────────────
interface ChartCardProps {
    title: string;
    icon: React.ReactNode;
    children: React.ReactNode;
    className?: string;
    badge?: React.ReactNode;
}

const ChartCard = ({ title, icon, children, className = '', badge }: ChartCardProps) => (
    <div className={`rounded-xl border border-border bg-card shadow-sm flex flex-col ${className}`}>
        <div className="flex items-center justify-between px-5 py-3.5 border-b border-border/60">
            <div className="flex items-center gap-2">
                <span className="text-primary/70">{icon}</span>
                <h2 className="text-sm font-semibold text-foreground">{title}</h2>
            </div>
            {badge}
        </div>
        <div className="p-5 flex-1">{children}</div>
    </div>
);

// ─────────────────────────────────────────────
// Tooltip
// ─────────────────────────────────────────────
const ChartTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null;
    return (
        <div className="bg-popover border border-border rounded-lg px-3 py-2 text-xs shadow-xl backdrop-blur-sm">
            {label && <p className="font-medium text-foreground mb-1.5">{label}</p>}
            {payload.map((p: any, i: number) => (
                <p key={i} className="font-semibold" style={{ color: p.color ?? p.fill }}>
                    {p.name}: <span className="text-foreground">{p.value}</span>
                </p>
            ))}
        </div>
    );
};

// ─────────────────────────────────────────────
// Empty state
// ─────────────────────────────────────────────
const Empty = () => (
    <div className="flex flex-col items-center justify-center gap-2 h-[160px] text-muted-foreground">
        <BarChart3 className="w-8 h-8 opacity-30" />
        <span className="text-sm">No data yet</span>
    </div>
);

// ─────────────────────────────────────────────
// Horizontal bar list (used for provider, pipeline, context)
// ─────────────────────────────────────────────
interface HBarListProps {
    data: Array<{ name: string; count: number }>;
    maxItems?: number;
    colorOffset?: number;
}

const HBarList = ({ data, maxItems = 5, colorOffset = 0 }: HBarListProps) => {
    const top = data.slice(0, maxItems);
    const max = top[0]?.count || 1;
    return (
        <div className="space-y-2.5">
            {top.map((item, i) => {
                const pct = Math.round((item.count / max) * 100);
                const color = CHART_COLORS[(i + colorOffset) % CHART_COLORS.length];
                return (
                    <div key={item.name}>
                        <div className="flex justify-between items-center text-xs mb-1">
                            <span className="truncate font-medium pr-2 max-w-[70%]" title={item.name}>{item.name}</span>
                            <span className="text-muted-foreground font-semibold flex-shrink-0">{item.count}</span>
                        </div>
                        <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                            <div
                                className="h-full rounded-full transition-all duration-700"
                                style={{ width: `${pct}%`, background: color }}
                            />
                        </div>
                    </div>
                );
            })}
        </div>
    );
};

// ─────────────────────────────────────────────
// Main Dashboard
// ─────────────────────────────────────────────
const Dashboard = () => {
    const [stats, setStats] = useState<CallStats | null>(null);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const fetchStats = useCallback(async () => {
        try {
            const end = new Date();
            const start = new Date();
            start.setDate(start.getDate() - 30);
            const res = await axios.get('/api/calls/stats', {
                params: {
                    start_date: start.toISOString().split('T')[0],
                    end_date: end.toISOString().split('T')[0],
                },
            });
            setStats(res.data);
            setLastUpdated(new Date());
        } catch (err) {
            console.error('Dashboard stats error:', err);
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }, []);

    useEffect(() => {
        fetchStats();
        const t = setInterval(fetchStats, 60_000);
        return () => clearInterval(t);
    }, [fetchStats]);

    // ── Derived data ─────────────────────────────────────
    const callsPerDayData = (stats?.calls_per_day ?? []).map(d => ({
        date: new Date(d.date).toLocaleDateString('en', { month: 'short', day: 'numeric' }),
        calls: d.count,
    }));

    const providerData = Object.entries(stats?.providers ?? {}).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));
    const pipelineData = Object.entries(stats?.pipelines ?? {}).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count }));
    const contextData = Object.entries(stats?.contexts ?? {}).sort((a, b) => b[1] - a[1]).map(([name, count]) => ({ name, count, value: count }));
    const outcomeData = Object.entries(stats?.outcomes ?? {}).map(([name, value]) => ({ name, value }));
    const topCallers = (stats?.top_callers ?? []).slice(0, 5).map(c => ({ name: c.number || 'Unknown', count: c.count }));

    const successRate = stats?.total_calls
        ? Math.round(((stats.outcomes?.completed ?? 0) / stats.total_calls) * 100)
        : 0;

    // ── Loading ──────────────────────────────────────────
    if (loading) {
        return (
            <div className="flex items-center justify-center h-[60vh]">
                <div className="flex flex-col items-center gap-3">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-primary" />
                    <p className="text-sm text-muted-foreground">Loading dashboard…</p>
                </div>
            </div>
        );
    }

    return (
        <div className="space-y-5 pb-10">

            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ROW 0 — Page header
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight">Dashboard</h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        30-day analytics overview
                        {lastUpdated && (
                            <span className="ml-2 opacity-60">
                                · updated {lastUpdated.toLocaleTimeString()}
                            </span>
                        )}
                    </p>
                </div>
                <button
                    onClick={() => { setRefreshing(true); fetchStats(); }}
                    disabled={refreshing}
                    className="flex items-center gap-2 px-4 py-2 rounded-lg border border-border bg-card hover:bg-accent text-sm font-medium transition-colors disabled:opacity-50 shadow-sm"
                >
                    <RefreshCw className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
                    Refresh
                </button>
            </div>

            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ROW 1 — 5 KPI cards
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-4">
                <KpiCard
                    title="Total Calls"
                    value={stats?.total_calls ?? 0}
                    sub={stats?.active_calls ? `${stats.active_calls} active now` : 'No active calls'}
                    icon={<Phone className="w-4 h-4" />}
                    accentBg="bg-blue-500/10" accentText="text-blue-500"
                    borderAccent="border-blue-500/20"
                />
                <KpiCard
                    title="Avg Duration"
                    value={formatDuration(stats?.avg_duration_seconds ?? 0)}
                    sub="Per completed call"
                    icon={<Timer className="w-4 h-4" />}
                    accentBg="bg-slate-500/10" accentText="text-slate-500"
                    borderAccent="border-slate-500/20"
                />
                <KpiCard
                    title="Avg Latency"
                    value={stats?.avg_latency_ms ? `${Math.round(stats.avg_latency_ms)} ms` : '-- ms'}
                    sub="Turn-to-turn response"
                    icon={<Zap className="w-4 h-4" />}
                    accentBg="bg-indigo-500/10" accentText="text-indigo-500"
                    borderAccent="border-indigo-500/20"
                />
                <KpiCard
                    title="Success Rate"
                    value={`${successRate}%`}
                    sub={`${stats?.outcomes?.completed ?? 0} completed calls`}
                    icon={<CheckCircle2 className="w-4 h-4" />}
                    accentBg="bg-emerald-500/10" accentText="text-emerald-500"
                    borderAccent="border-emerald-500/20"
                />
                <KpiCard
                    title="Unique Callers"
                    value={stats?.top_callers?.length ?? 0}
                    sub="Distinct numbers"
                    icon={<Users className="w-4 h-4" />}
                    accentBg="bg-sky-500/10" accentText="text-sky-500"
                    borderAccent="border-sky-500/20"
                />
            </div>

            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ROW 2 — Area chart (full width)
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            <ChartCard
                title="Calls per Day — Last 30 Days"
                icon={<Activity className="w-4 h-4" />}
                badge={
                    <span className="text-xs text-muted-foreground bg-muted px-2 py-0.5 rounded-full">
                        {stats?.total_calls ?? 0} total
                    </span>
                }
            >
                {callsPerDayData.length === 0 ? <Empty /> : (
                    <ResponsiveContainer width="100%" height={200}>
                        <AreaChart data={callsPerDayData} margin={{ top: 4, right: 8, left: -22, bottom: 0 }}>
                            <defs>
                                <linearGradient id="grad-calls" x1="0" y1="0" x2="0" y2="1">
                                    <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.2} />
                                    <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.01} />
                                </linearGradient>
                            </defs>
                            <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
                            <XAxis dataKey="date" tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} interval="preserveStartEnd" />
                            <YAxis tick={{ fontSize: 11, fill: 'hsl(var(--muted-foreground))' }} axisLine={false} tickLine={false} allowDecimals={false} />
                            <Tooltip content={<ChartTooltip />} />
                            <Area type="monotone" dataKey="calls" stroke="#3b82f6" strokeWidth={2} fill="url(#grad-calls)" dot={false} activeDot={{ r: 5, fill: '#3b82f6', strokeWidth: 0 }} />
                        </AreaChart>
                    </ResponsiveContainer>
                )}
            </ChartCard>

            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ROW 3 — Provider | Pipeline | Outcomes
                3-column equal grid
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

                {/* Provider */}
                <ChartCard title="Top Providers" icon={<BarChart3 className="w-4 h-4" />}>
                    {providerData.length === 0 ? <Empty /> : (
                        <HBarList data={providerData} colorOffset={0} />
                    )}
                </ChartCard>

                {/* Pipeline */}
                <ChartCard title="Top Pipelines" icon={<BarChart3 className="w-4 h-4" />}>
                    {pipelineData.length === 0 ? <Empty /> : (
                        <HBarList data={pipelineData} colorOffset={2} />
                    )}
                </ChartCard>

                {/* Outcomes donut */}
                <ChartCard title="Call Outcomes" icon={<TrendingUp className="w-4 h-4" />}>
                    {outcomeData.length === 0 ? <Empty /> : (
                        <div className="flex flex-col items-center gap-3">
                            <ResponsiveContainer width="100%" height={150}>
                                <PieChart>
                                    <Pie data={outcomeData} cx="50%" cy="50%" innerRadius={42} outerRadius={68} paddingAngle={3} dataKey="value" startAngle={90} endAngle={-270}>
                                        {outcomeData.map((entry, i) => (
                                            <Cell key={entry.name} fill={OUTCOME_COLORS[entry.name] ?? CHART_COLORS[i % CHART_COLORS.length]} />
                                        ))}
                                    </Pie>
                                    <Tooltip content={<ChartTooltip />} />
                                </PieChart>
                            </ResponsiveContainer>
                            <div className="w-full space-y-1.5">
                                {outcomeData.map((entry, i) => (
                                    <div key={entry.name} className="flex items-center gap-2 text-xs">
                                        <span className="w-2 h-2 rounded-full flex-shrink-0"
                                            style={{ background: OUTCOME_COLORS[entry.name] ?? CHART_COLORS[i % CHART_COLORS.length] }} />
                                        <span className="capitalize text-muted-foreground">{entry.name}</span>
                                        <span className="ml-auto font-semibold">{entry.value}</span>
                                        <span className="text-muted-foreground/60">
                                            {stats?.total_calls ? `${Math.round((entry.value / stats.total_calls) * 100)}%` : ''}
                                        </span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </ChartCard>
            </div>

            {/* ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
                ROW 4 — Context pie | Top callers | Performance
                3-column equal grid
            ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ */}
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">

                {/* Context */}
                <ChartCard title="Calls by Context" icon={<PieChartIcon className="w-4 h-4" />}>
                    {contextData.length === 0 ? <Empty /> : (
                        <div className="flex flex-col items-center gap-3">
                            <ResponsiveContainer width="100%" height={150}>
                                <PieChart>
                                    <Pie data={contextData} cx="50%" cy="50%" outerRadius={68} paddingAngle={3} dataKey="value">
                                        {contextData.map((_, i) => (
                                            <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
                                        ))}
                                    </Pie>
                                    <Tooltip content={<ChartTooltip />} />
                                </PieChart>
                            </ResponsiveContainer>
                            <div className="w-full space-y-1.5">
                                {contextData.slice(0, 5).map((c, i) => (
                                    <div key={c.name} className="flex items-center gap-2 text-xs">
                                        <span className="w-2 h-2 rounded-full flex-shrink-0" style={{ background: CHART_COLORS[i % CHART_COLORS.length] }} />
                                        <span className="truncate text-muted-foreground" title={c.name}>{c.name}</span>
                                        <span className="ml-auto font-semibold">{c.count}</span>
                                    </div>
                                ))}
                            </div>
                        </div>
                    )}
                </ChartCard>

                {/* Top callers */}
                <ChartCard title="Most Called Numbers" icon={<PhoneCall className="w-4 h-4" />}>
                    {topCallers.length === 0 ? <Empty /> : (
                        <HBarList data={topCallers} colorOffset={4} />
                    )}
                </ChartCard>

                {/* Performance summary */}
                <ChartCard title="Performance Summary" icon={<Zap className="w-4 h-4" />}>
                    <div className="space-y-4">
                        {/* Latency */}
                        <div className="rounded-lg bg-indigo-500/5 border border-indigo-500/15 p-4 flex items-center gap-4">
                            <div className="bg-indigo-500/10 text-indigo-500 p-3 rounded-xl">
                                <Zap className="w-5 h-5" />
                            </div>
                            <div>
                                <div className="text-2xl font-bold text-indigo-500 tracking-tight">
                                    {stats?.avg_latency_ms ? `${Math.round(stats.avg_latency_ms)} ms` : '-- ms'}
                                </div>
                                <div className="text-xs text-muted-foreground">Avg turn latency</div>
                            </div>
                        </div>

                        {/* Duration */}
                        <div className="rounded-lg bg-slate-500/5 border border-slate-500/15 p-4 flex items-center gap-4">
                            <div className="bg-slate-500/10 text-slate-500 p-3 rounded-xl">
                                <Timer className="w-5 h-5" />
                            </div>
                            <div>
                                <div className="text-2xl font-bold text-slate-500 tracking-tight">
                                    {formatDuration(stats?.avg_duration_seconds ?? 0)}
                                </div>
                                <div className="text-xs text-muted-foreground">Avg call duration</div>
                            </div>
                        </div>

                        {/* Success rate bar */}
                        <div className="space-y-2">
                            <div className="flex justify-between text-xs">
                                <span className="text-muted-foreground">Success rate</span>
                                <span className="font-semibold text-emerald-500">{successRate}%</span>
                            </div>
                            <div className="h-2 w-full bg-muted rounded-full overflow-hidden">
                                <div
                                    className="h-full rounded-full bg-emerald-500 transition-all duration-700"
                                    style={{ width: `${successRate}%` }}
                                />
                            </div>
                        </div>
                    </div>
                </ChartCard>
            </div>
        </div>
    );
};

export default Dashboard;
