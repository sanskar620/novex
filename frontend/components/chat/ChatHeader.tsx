"use client";

import { useEffect, useState } from "react";
import {
  Cpu,
  Download,
  FileJson,
  Globe,
  Menu,
  MoreHorizontal,
  PanelLeft,
  Share2,
  ShieldAlert,
} from "lucide-react";
import { deleteSession, reportGeoJsonUrl, reportPdfUrl } from "@/lib/api";
import { useT } from "@/lib/i18n";
import { useAppStore } from "@/lib/store";
import { cn } from "@/lib/utils";
import { ThemeToggle } from "@/components/ui/ThemeToggle";
import { useTheme } from "@/lib/theme";
import { GpuNodeModal } from "./GpuNodeModal";

interface ChatHeaderProps {
  onToggleMobileSidebar: () => void;
  isOpenDesktop?: boolean;
  onToggleDesktop?: () => void;
  activeTask?: string;
}

export function ChatHeader({
  onToggleMobileSidebar,
  isOpenDesktop = true,
  onToggleDesktop,
  activeTask,
}: ChatHeaderProps) {
  const sessionId = useAppStore((s) => s.sessionId);
  const activeSessionTitle = useAppStore((s) => s.activeSessionTitle);
  const setActiveSessionTitle = useAppStore((s) => s.setActiveSessionTitle);
  const isTemporaryChat = useAppStore((s) => s.isTemporaryChat);
  const setIsTemporaryChat = useAppStore((s) => s.setIsTemporaryChat);
  const setShareModalOpen = useAppStore((s) => s.setShareModalOpen);
  const setMapModalOpen = useAppStore((s) => s.setMapModalOpen);
  const lastResult = useAppStore((s) => s.lastResult);
  const resetConversationState = useAppStore((s) => s.resetConversationState);
  const setSessionId = useAppStore((s) => s.setSessionId);
  const [optionsOpen, setOptionsOpen] = useState(false);
  const [gpuModalOpen, setGpuModalOpen] = useState(false);
  const [isGpuConnected, setIsGpuConnected] = useState(false);
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
    if (typeof window !== "undefined") {
      const custom = localStorage.getItem("satquery_custom_gpu_url");
      setIsGpuConnected(Boolean(custom && custom.trim()));
    }
  }, [gpuModalOpen]);
  const { t } = useT();
  const { resolvedTheme } = useTheme();
  const isLight = resolvedTheme === "light";

  function handleToggleTemporary() {
    if (!isTemporaryChat) {
      resetConversationState();
      setIsTemporaryChat(true);
      setSessionId(`temp-${Date.now()}`);
      setActiveSessionTitle("Temporary chat");
    } else {
      // A temporary chat still creates a real backend session under the
      // hood the moment a message is sent (the query pipeline requires one
      // to attach messages/executions to) -- "won't be saved... discarded
      // when closed" only holds true if leaving temporary mode actually
      // deletes it, rather than leaving it orphaned in the database.
      const hadRealSession = sessionId && sessionId !== "session-new" && !sessionId.startsWith("temp-");
      if (hadRealSession) {
        deleteSession(sessionId as string).catch(() => {
          // Best-effort cleanup -- nothing actionable to show the user here.
        });
      }
      resetConversationState();
      setIsTemporaryChat(false);
      setSessionId("session-new");
      setActiveSessionTitle("New Satellite Query");
    }
  }

  return (
    <header className={`flex h-14 w-full items-center justify-between border-b ${isLight ? "border-black/10 bg-[#f5f2eb]/90 text-[#18181b]" : "border-[#1f1f1f] bg-[#000000]/80 text-white"} backdrop-blur-md px-4 sm:px-6 sticky top-0 z-30 select-none transition-colors duration-200`}>
      {/* Left section */}
      <div className="flex items-center gap-3 min-w-0">
        {/* Mobile menu button */}
        <button
          type="button"
          onClick={onToggleMobileSidebar}
          className={`md:hidden p-1.5 rounded-lg transition-colors ${isLight ? "text-neutral-600 hover:text-black hover:bg-black/5" : "text-[#737373] hover:text-white hover:bg-[#1a1a1a]"}`}
          aria-label="Open Sidebar"
        >
          <Menu className="h-5 w-5" />
        </button>

        {/* Desktop Expand Button when sidebar is collapsed */}
        {!isOpenDesktop && onToggleDesktop && (
          <button
            type="button"
            onClick={onToggleDesktop}
            className={`hidden md:flex p-1.5 rounded-lg transition-colors shrink-0 ${isLight ? "text-neutral-600 hover:text-black hover:bg-black/5" : "text-[#737373] hover:text-white hover:bg-[#1a1a1a]"}`}
            aria-label="Open Sidebar (⌘B)"
            title="Open Sidebar (⌘B)"
          >
            <PanelLeft className="w-4 h-4" />
          </button>
        )}

        {/* Title & Task Tag */}
        <div className="flex items-center gap-2.5 min-w-0">
          <h1 className={`text-xs sm:text-sm font-medium truncate font-sans ${isLight ? "text-[#18181b]" : "text-white"}`}>
            {activeSessionTitle || "New Satellite Query"}
          </h1>

          {activeTask && (
            <span className={`hidden sm:inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-mono ${isLight ? "bg-black/5 border border-black/10 text-neutral-600" : "bg-[#171717] border border-[#2a2a2a] text-[#a3a3a3]"}`}>
              {activeTask}
            </span>
          )}

          {isTemporaryChat && (
            <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium ${isLight ? "bg-amber-500/10 border border-amber-500/20 text-amber-800" : "bg-[#221f14] border border-[#443818] text-[#d4b152]"}`}>
              <ShieldAlert className="w-3 h-3" />
              {t("header.temporary")}
            </span>
          )}
        </div>
      </div>

      {/* Right Controls */}
      <div className="relative flex items-center gap-2 text-xs font-sans">
        {/* Backend Node Selector */}
        <button
          type="button"
          onClick={() => setGpuModalOpen(true)}
          suppressHydrationWarning
          className={`flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl border text-[11px] font-mono shadow-subtle transition-all cursor-pointer ${
            mounted && isGpuConnected
              ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400 hover:bg-emerald-500/20"
              : isLight
                ? "bg-[#ede8df] hover:bg-black/5 border-black/10 text-neutral-700"
                : "bg-[#141414] hover:bg-white/5 border-white/10 text-neutral-300"
          }`}
          title="Click to toggle or connect Kaggle GPU / Cloudflare URL"
        >
          <span
            className={`w-1.5 h-1.5 rounded-full ${
              mounted && isGpuConnected ? "bg-emerald-400 animate-pulse" : "bg-blue-400"
            }`}
          />
          <Cpu className="w-3.5 h-3.5" />
          <span className="inline font-medium">
            {mounted && isGpuConnected ? "GPU (Kaggle)" : "24/7 (Render)"}
          </span>
        </button>

        {/* Theme Toggle (Default / Light / Dark) */}
        <ThemeToggle />

        {/* Temporary Toggle Button */}
        <button
          type="button"
          onClick={handleToggleTemporary}
          className={cn(
            "flex items-center gap-1.5 px-2.5 py-1.5 rounded-xl text-xs transition-all font-medium border",
            isTemporaryChat
              ? isLight
                ? "bg-black/10 text-neutral-900 border-black/20 shadow-subtle"
                : "bg-[#262626] text-white border-[#444444] shadow-subtle"
              : isLight
                ? "bg-transparent text-neutral-600 hover:text-neutral-900 border-transparent hover:bg-black/5"
                : "bg-transparent text-[#737373] hover:text-white border-transparent hover:bg-[#171717]"
          )}
          title={isTemporaryChat ? "Temporary chat enabled (will discard when switching)" : "Enable temporary chat"}
        >
          <span
            className={cn(
              "w-1.5 h-1.5 rounded-full transition-colors",
              isTemporaryChat ? (isLight ? "bg-black" : "bg-white") : (isLight ? "bg-neutral-400" : "bg-[#525252]")
            )}
          />
          <span className="hidden sm:inline">{t("header.temporary")}</span>
        </button>

        {/* Share Button */}
        <button
          type="button"
          onClick={() => setShareModalOpen(true)}
          className={`flex items-center gap-1.5 px-3 py-1.5 rounded-xl text-xs font-medium transition-colors shadow-subtle border ${isLight
              ? "bg-[#fcfbf8] hover:bg-white text-neutral-800 border-black/10 shadow-sm"
              : "bg-[#171717] hover:bg-[#212121] text-[#e5e5e5] hover:text-white border border-[#2e2e2e]"
            }`}
        >
          <Share2 className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">{t("header.share")}</span>
        </button>

        {/* More Options Menu */}
        <div className="relative">
          <button
            type="button"
            onClick={() => setOptionsOpen(!optionsOpen)}
            className={`flex h-8 w-8 items-center justify-center rounded-lg transition-colors ${isLight ? "text-neutral-600 hover:bg-black/5 hover:text-neutral-900" : "text-neutral-400 hover:bg-white/10 hover:text-white"
              }`}
            aria-label="More options"
          >
            <MoreHorizontal className="h-4 w-4" />
          </button>

          {optionsOpen && (
            <div className={`absolute right-0 top-10 z-40 w-56 rounded-2xl border p-1.5 shadow-2xl animate-in fade-in zoom-in-95 duration-100 font-sans text-xs ${isLight
                ? "border-black/10 bg-[#fcfbf8] text-neutral-800 shadow-xl"
                : "border-[#303030] bg-[#171717] text-neutral-300"
              }`}>
              <button
                type="button"
                onClick={() => {
                  setMapModalOpen(true);
                  setOptionsOpen(false);
                }}
                className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs transition-colors text-left ${isLight
                    ? "text-neutral-700 hover:bg-black/5 hover:text-neutral-950"
                    : "text-neutral-200 hover:bg-white/10 hover:text-white"
                  }`}
              >
                <Globe className={`h-4 w-4 ${isLight ? "text-neutral-500" : "text-neutral-400"}`} />
                <span>{t("header.inspectMap")}</span>
              </button>

              {/* Export shortcuts if a completed execution exists. The backend
                  itself refuses (409) a GeoJSON export for an execution with no
                  real georeferenced geometry -- no need to duplicate that check
                  here, just don't pretend export always succeeds silently. */}
              {lastResult?.execution_id && (
                <>
                  <div className={`my-1 border-t ${isLight ? "border-black/10" : "border-white/10"}`} />
                  <a
                    href={reportGeoJsonUrl(lastResult.execution_id)}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => setOptionsOpen(false)}
                    className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs transition-colors text-left ${isLight
                        ? "text-neutral-700 hover:bg-black/5 hover:text-neutral-950"
                        : "text-neutral-200 hover:bg-white/10 hover:text-white"
                      }`}
                  >
                    <FileJson className={`h-4 w-4 ${isLight ? "text-neutral-500" : "text-neutral-400"}`} />
                    <span>{t("header.downloadGeojson")}</span>
                  </a>
                  <a
                    href={reportPdfUrl(lastResult.execution_id)}
                    target="_blank"
                    rel="noreferrer"
                    onClick={() => setOptionsOpen(false)}
                    className={`flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-xs transition-colors text-left ${isLight
                        ? "text-neutral-700 hover:bg-black/5 hover:text-neutral-950"
                        : "text-neutral-200 hover:bg-white/10 hover:text-white"
                      }`}
                  >
                    <Download className={`h-4 w-4 ${isLight ? "text-neutral-500" : "text-neutral-400"}`} />
                    <span>{t("header.downloadPdf")}</span>
                  </a>
                </>
              )}
            </div>
          )}
        </div>
      </div>
      <GpuNodeModal isOpen={gpuModalOpen} onClose={() => setGpuModalOpen(false)} />
    </header>
  );
}
