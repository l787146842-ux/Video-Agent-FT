export type CanvasColorTheme = "light" | "dark";
export type CanvasBackgroundMode = "dots" | "lines" | "blank";

/**
 * 画布色板（对齐本项目 src/web/styles/tokens.css）。
 *
 * 本地 patch（L1 主题对齐）：原色板为暖灰（stone 系，#181715/#292524），
 * 与外层冷蓝灰界面并置像两套产品；此处改用本项目 token 的等值色，
 * 仅换配色不改布局。上游合并时本文件属预期冲突点。
 */
export const canvasThemes = {
    light: {
        canvas: {
            background: "#f5f6f8", // --bg-primary (light)
            dot: "rgba(31,41,55,.22)", // --text-main (light) 透明档
            line: "rgba(31,41,55,.09)",
            selectionStroke: "#3b82f6", // --accent-blue
            selectionFill: "rgba(59,130,246,.08)",
        },
        node: {
            label: "#6b7280", // --text-muted (light)
            fill: "#eef0f4", // --bg-tertiary (light)
            panel: "#ffffff", // --bg-secondary (light)
            stroke: "#d9dce3", // --border-color (light)
            activeStroke: "#3b82f6", // --accent-blue
            placeholder: "#9ca3af", // --text-dim (light)
            text: "#1f2937", // --text-main (light)
            muted: "#6b7280",
            faint: "#9ca3af",
        },
        toolbar: {
            panel: "rgba(255,255,255,.96)", // --bg-secondary (light)
            border: "#d9dce3",
            item: "#6b7280",
            itemHover: "#eef0f4",
            activeBg: "#eef0f4",
            activeText: "#1f2937",
        },
    },
    dark: {
        canvas: {
            background: "#121319", // --bg-primary
            dot: "rgba(243,244,246,.18)", // --text-main 透明档
            line: "rgba(243,244,246,.07)",
            selectionStroke: "#3b82f6", // --accent-blue
            selectionFill: "rgba(59,130,246,.12)",
        },
        node: {
            label: "#9ca3af", // --text-muted
            fill: "#1e212b", // --bg-card
            panel: "#1a1c24", // --bg-secondary
            stroke: "#2e3346", // --border-color
            activeStroke: "#3b82f6", // --accent-blue
            placeholder: "#6b7280", // --text-dim
            text: "#f3f4f6", // --text-main
            muted: "#9ca3af",
            faint: "#6b7280",
        },
        toolbar: {
            panel: "rgba(26,28,36,.96)", // --bg-secondary 透明档
            border: "#2e3346",
            item: "#9ca3af",
            itemHover: "#2c3040", // --bg-hover
            activeBg: "#232633", // --bg-tertiary
            activeText: "#f3f4f6",
        },
    },
} as const;

export type CanvasTheme = (typeof canvasThemes)[CanvasColorTheme];
