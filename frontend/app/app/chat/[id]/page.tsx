"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
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

export default function ChatDetailPage() {
  const params = useParams();
  const chatId = Array.isArray(params?.id) ? params.id[0] : params?.id;

  const sessionId = useAppStore((s) => s.sessionId);
  const setSessionId = useAppStore((s) => s.setSessionId);
  const resetConversationState = useAppStore((s) => s.resetConversationState);
  const { resolvedTheme } = useTheme();
  const isLight = resolvedTheme === "light";

  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);
  const [conversations, setConversations] = useState<ConversationSummaryItem[]>(
    MOCK_SESSIONS.map((s) => ({
      id: s.id,
      title: s.title,
      category: s.category,
    }))
  );

  function refreshSessions() {
    listSessions()
      .then((sessions) => {
        setConversations(
          sessions.map((s) => ({
            id: s.id,
            title: s.title || "Untitled Analysis",
            category: categorize(s.created_at),
          }))
        );
      })
      .catch(() => {
        // Backend unreachable -- sidebar just shows no history until it's back.
      });
  }

  useEffect(() => {
    if (chatId) {
      setSessionId(chatId);
    }
  }, [chatId, setSessionId]);

  const sessionRefreshTrigger = useAppStore((s) => s.sessionRefreshTrigger);
  useEffect(() => {
    refreshSessions();
  }, [sessionId, sessionRefreshTrigger]);

  function handleSelectConversation(id: string) {
    setSessionId(id);
    setMobileSidebarOpen(false);
  }

  function handleNewChat() {
    resetConversationState();
    setMobileSidebarOpen(false);
  }

  function handleDeleteConversation(id: string) {
    const previous = conversations;
    setConversations((prev) => prev.filter((c) => c.id !== id));
    if (sessionId === id) {
      resetConversationState();
    }
    deleteSession(id).catch(() => {
      setConversations(previous);
    });
  }

  function handleRenameConversation(id: string, newTitle: string) {
    const previous = conversations;
    setConversations((prev) =>
      prev.map((c) => (c.id === id ? { ...c, title: newTitle } : c))
    );
    renameSession(id, newTitle).catch(() => {
      setConversations(previous);
    });
  }

  return (
    <div className={`chat-workspace flex h-screen w-screen overflow-hidden ${isLight ? "bg-[#f5f2eb] text-[#18181b]" : "bg-[#080808] text-neutral-100"} font-sans selection:bg-white selection:text-black transition-colors duration-200`}>
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
      <ChatSidebar
        conversations={conversations}
        activeId={sessionId}
        onSelectConversation={handleSelectConversation}
        onNewChat={handleNewChat}
        onDeleteConversation={handleDeleteConversation}
        onRenameConversation={handleRenameConversation}
        isOpenMobile={mobileSidebarOpen}
        onCloseMobile={() => setMobileSidebarOpen(false)}
      />

      {mobileSidebarOpen && (
        <div
          onClick={() => setMobileSidebarOpen(false)}
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm md:hidden"
        />
      )}

      <div className="flex flex-1 flex-col h-full min-w-0 overflow-hidden">
        <ChatHeader onToggleMobileSidebar={() => setMobileSidebarOpen(true)} />
        <ChatArea initialSessionId={chatId} />
      </div>

      <ShareModal />
      <SatelliteMapModal />
      <EvidenceModal />
    </div>
  );
}
