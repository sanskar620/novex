"use client";

import { useEffect, useState } from "react";
import { ChatArea } from "@/components/chat/ChatArea";
import { ChatHeader } from "@/components/chat/ChatHeader";
import { ChatSidebar, type ConversationSummaryItem } from "@/components/chat/ChatSidebar";
import { SatelliteMapModal } from "@/components/chat/SatelliteMapModal";
import { ShareModal } from "@/components/chat/ShareModal";
import { EvidenceModal } from "@/components/chat/EvidenceModal";
import { deleteSession, listSessions, renameSession } from "@/lib/api";
import { MOCK_SESSIONS } from "@/lib/mock-data";
import { useAppStore } from "@/lib/store";
import { useTheme } from "@/lib/theme";

function categorize(createdAt: string): ConversationSummaryItem["category"] {
  const created = new Date(createdAt);
  const now = new Date();
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const daysAgo = Math.round((startOfDay(now) - startOfDay(created)) / 86_400_000);
  if (daysAgo <= 0) return "Today";
  if (daysAgo === 1) return "Yesterday";
  if (daysAgo <= 7) return "Previous 7 Days";
  return "Older";
}

export default function WorkspacePage() {
  const sessionId = useAppStore((s) => s.sessionId);
  const setSessionId = useAppStore((s) => s.setSessionId);
  const setActiveSessionTitle = useAppStore((s) => s.setActiveSessionTitle);
  const resetConversationState = useAppStore((s) => s.resetConversationState);
  const { resolvedTheme } = useTheme();
  const isLight = resolvedTheme === "light";


  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [desktopSidebarOpen, setDesktopSidebarOpen] = useState(true);
  const [conversations, setConversations] = useState<ConversationSummaryItem[]>(() => {
    if (typeof window !== "undefined") {
      try {
        const cached = localStorage.getItem("satquery_conversations_cache");
        if (cached) {
          const parsed = JSON.parse(cached);
          if (Array.isArray(parsed) && parsed.length > 0) return parsed;
        }
      } catch {
        // ignore
      }
    }
    return MOCK_SESSIONS.map((s) => ({
      id: s.id,
      title: s.title,
      category: s.category,
    }));
  });

  // Global keyboard shortcuts (Cmd+B to toggle sidebar, Cmd+N for new chat)
  useEffect(() => {
    function handleKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "b") {
        e.preventDefault();
        setDesktopSidebarOpen((prev) => !prev);
      }
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "n") {
        e.preventDefault();
        resetConversationState();
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [resetConversationState]);

  function refreshSessions() {
    listSessions()
      .then((sessions) => {
        const fetched = sessions.map((s) => ({
          id: s.id,
          title: s.title || "Untitled Analysis",
          category: categorize(s.created_at),
        }));
        if (typeof window !== "undefined") {
          try {
            const localSaved: ConversationSummaryItem[] = JSON.parse(
              localStorage.getItem("satquery_local_sessions") || "[]"
            );
            const fetchedIds = new Set(fetched.map((f) => f.id));
            const merged = [...fetched, ...localSaved.filter((l) => !fetchedIds.has(l.id))];
            setConversations(merged);
            localStorage.setItem("satquery_conversations_cache", JSON.stringify(merged));
            return;
          } catch {
            // ignore
          }
        }
        setConversations(fetched);
      })
      .catch(() => {
        // Backend unreachable -- restore from local cache or fallback list
        if (typeof window !== "undefined") {
          try {
            const cached = localStorage.getItem("satquery_conversations_cache");
            const localSaved = localStorage.getItem("satquery_local_sessions");
            const combined = [
              ...(localSaved ? JSON.parse(localSaved) : []),
              ...(cached ? JSON.parse(cached) : []),
            ];
            if (combined.length > 0) {
              const unique = Array.from(new Map(combined.map((c) => [c.id, c])).values());
              setConversations(unique);
            }
          } catch {
            // ignore
          }
        }
      });
  }

  // Re-syncs whenever the active session changes -- covers both picking an
  // existing conversation (harmless no-op refresh) and a brand-new session
  // getting created on the first message of a chat (picks it up for the list).
  useEffect(() => {
    refreshSessions();
  }, [sessionId]);

  function handleSelectConversation(id: string) {
    if (useAppStore.getState().isTemporaryChat) {
      resetConversationState();
      useAppStore.getState().setIsTemporaryChat(false);
    }
    setSessionId(id);
    const found = conversations.find((c) => c.id === id);
    if (found) {
      setActiveSessionTitle(found.title);
    }
    setMobileSidebarOpen(false);
  }

  function handleNewChat() {
    // Reset to "session-new" -- the same not-yet-created placeholder the
    // app starts on -- and let ensureSession() (ChatArea.tsx) lazily create
    // the real backend session on the first actual message/upload, exactly
    // like the initial landing state already does correctly.
    //
    // This used to fabricate its own `session-${Date.now()}` id and store
    // it as the active session directly. ensureSession()'s "already have a
    // real session" check only excludes the literal "session-new" and
    // "temp-*" placeholders, so that fabricated id slipped past it as if
    // it were real, skipping createSession() entirely -- every subsequent
    // upload/query then submitted a session_id nothing in the database
    // matched, surfacing as "Session '...' does not exist."
    if (useAppStore.getState().isTemporaryChat) {
      useAppStore.getState().setIsTemporaryChat(false);
    }
    resetConversationState();
    setActiveSessionTitle("New Satellite Query");
    setMobileSidebarOpen(false);
  }

  function handleDeleteConversation(id: string) {
    const previous = conversations;
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (sessionId === id) {
      handleNewChat();
    }
    deleteSession(id).catch(() => {
      setConversations(previous); // backend rejected/unreachable -- restore
    });
  }

  function handleRenameConversation(id: string, newTitle: string) {
    const previous = conversations;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title: newTitle } : c))
    );
    if (sessionId === id) {
      setActiveSessionTitle(newTitle);
    }
    renameSession(id, newTitle).catch(() => {
      setConversations(previous); // backend rejected/unreachable -- restore
    });
  }


  return (
    <div className={`chat-workspace flex h-screen w-screen overflow-hidden ${isLight ? "bg-[#f5f2eb] text-[#18181b]" : "bg-[#000000] text-neutral-100"} font-sans selection:bg-white selection:text-black transition-colors duration-200`}>
      <style>{`
        .chat-workspace ::-webkit-scrollbar,
        .chat-workspace::-webkit-scrollbar,
        .chat-workspace *::-webkit-scrollbar {
          display: none !important;
          width: 0 !important;
          height: 0 !important;
        }
        .chat-workspace ::-webkit-scrollbar-thumb,
        .chat-workspace::-webkit-scrollbar-thumb,
        .chat-workspace *::-webkit-scrollbar-thumb {
          background: transparent !important;
          display: none !important;
        }
        .chat-workspace,
        .chat-workspace * {
          scrollbar-width: none !important;
          -ms-overflow-style: none !important;
        }
      `}</style>
      {/* Sidebar (Desktop + Mobile Drawer) */}
      <ChatSidebar
        conversations={conversations}
        activeId={sessionId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        onRenameConversation={handleRenameConversation}
        isOpenDesktop={desktopSidebarOpen}
        onToggleDesktop={() => setDesktopSidebarOpen((prev) => !prev)}
        isOpenMobile={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {/* Backdrop for Mobile Sidebar Drawer */}
      {mobileSidebarOpen && (
        <div
          onClick={() => setMobileSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
        />
      )}

      {/* Main Chat Workspace */}
      <div className="flex flex-1 flex-col h-full min-w-0 overflow-hidden">
        <ChatHeader
          onToggleMobileSidebar={() => setMobileSidebarOpen(true)}
          isOpenDesktop={desktopSidebarOpen}
          onToggleDesktop={() => setDesktopSidebarOpen((prev) => !prev)}
        />
        <ChatArea />
      </div>

      {/* Global Modals */}
      <ShareModal />
      <SatelliteMapModal />
      <EvidenceModal />
    </div>
  );
}

