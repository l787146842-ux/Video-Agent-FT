import type { ReactNode } from "react";

import { LocalAgentPanel } from "@/components/agent/local-agent-panel";
import { AppTopNav } from "@/components/layout/app-top-nav";

export default function UserLayout({ children }: { children: ReactNode }) {
    return (
        <div className="flex h-dvh overflow-hidden bg-background text-foreground">
            <div className="flex min-w-0 flex-1 flex-col overflow-hidden">
                <AppTopNav />
                <div className="min-h-0 flex-1 overflow-hidden">{children}</div>
            </div>
            {/* 画布内 agent 界面由外层本项目 RightPanel 接管（L1）：
                headless 只保留 SSE 连接与工具执行器，不渲染任何面板 UI。 */}
            <LocalAgentPanel headless autoConnect />
        </div>
    );
}
