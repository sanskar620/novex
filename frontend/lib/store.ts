import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { UILanguage } from "./i18n";
import type { ExecutionResult } from "./types";

export interface PendingAttachment {
  id: string;
  file?: File;
  previewUrl: string;
  name: string;
  sizeBytes?: number;
  type: "optical" | "sar" | "multispectral" | "unknown";
  role?: "before" | "after" | "optical" | "sar" | "single";
  sensor?: string;
  resolution?: string;
}

interface AppState {
  sessionId: string | null;
  activeSessionTitle: string;
  imageIds: string[];
  pendingAttachments: PendingAttachment[];
  lastResult: ExecutionResult | null;
  isTemporaryChat: boolean;
  shareModalOpen: boolean;
  mapModalOpen: boolean;
  activeEvidenceImage: { url: string; label?: string } | null;
  evidenceModalData: {
    title: string;
    image: string;
    metrics?: { label: string; value: string; change?: string }[];
  } | null;
  uiLanguage: UILanguage;
  sessionRefreshTrigger: number;

  setUiLanguage: (language: UILanguage) => void;
  triggerSessionRefresh: () => void;
  setSessionId: (id: string | null) => void;
  setActiveSessionTitle: (title: string) => void;
  addImageId: (id: string) => void;
  clearImages: () => void;
  addPendingAttachment: (attachment: PendingAttachment) => void;
  removePendingAttachment: (id: string) => void;
  clearPendingAttachments: () => void;
  setLastResult: (result: ExecutionResult | null) => void;
  setIsTemporaryChat: (isTemp: boolean) => void;
  setShareModalOpen: (open: boolean) => void;
  setMapModalOpen: (open: boolean) => void;
  setActiveEvidenceImage: (img: { url: string; label?: string } | null) => void;
  setEvidenceModalData: (
    data: {
      title: string;
      image: string;
      metrics?: { label: string; value: string; change?: string }[];
    } | null
  ) => void;
  resetConversationState: () => void;
}

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      sessionId: "session-new",
      activeSessionTitle: "New Satellite Query",
      imageIds: [],
      pendingAttachments: [],
      lastResult: null,
      isTemporaryChat: false,
      shareModalOpen: false,
      mapModalOpen: false,
      activeEvidenceImage: null,
      evidenceModalData: null,
      uiLanguage: "en",
      sessionRefreshTrigger: 0,

      setUiLanguage: (language) => set({ uiLanguage: language }),
      triggerSessionRefresh: () =>
        set((state) => ({ sessionRefreshTrigger: state.sessionRefreshTrigger + 1 })),
      setSessionId: (id) => set({ sessionId: id }),
      setActiveSessionTitle: (title) => set({ activeSessionTitle: title }),
      addImageId: (id) => set((state) => ({ imageIds: [...state.imageIds, id] })),
      clearImages: () => set({ imageIds: [] }),
      addPendingAttachment: (attachment) =>
        set((state) => ({
          pendingAttachments: [...state.pendingAttachments, attachment],
        })),
      removePendingAttachment: (id) =>
        set((state) => ({
          pendingAttachments: state.pendingAttachments.filter((a) => a.id !== id),
        })),
      clearPendingAttachments: () => set({ pendingAttachments: [] }),
      setLastResult: (result) => set({ lastResult: result }),
      setIsTemporaryChat: (isTemp) => set({ isTemporaryChat: isTemp }),
      setShareModalOpen: (open) => set({ shareModalOpen: open }),
      setMapModalOpen: (open) => set({ mapModalOpen: open }),
      setActiveEvidenceImage: (img) => set({ activeEvidenceImage: img }),
      setEvidenceModalData: (data) => set({ evidenceModalData: data }),
      resetConversationState: () =>
        set({
          sessionId: "session-new",
          activeSessionTitle: "New Satellite Query",
          imageIds: [],
          pendingAttachments: [],
          lastResult: null,
          isTemporaryChat: false,
        }),
    }),
    {
      name: "satquery-ui",
      // sessionId/activeSessionTitle are only persisted for a real (non-
      // temporary) session -- without this, refreshing /app forgot which
      // conversation was open (it wasn't in localStorage, only uiLanguage
      // was), so the UI fell back to a placeholder id that fetches nothing
      // and the visible chat went blank even though it was safe in the
      // database the whole time. A temporary chat must NOT survive a
      // refresh -- that's the point of "temporary" -- so it's excluded here
      // rather than persisted and cleaned up later.
      partialize: (state) => ({
        uiLanguage: state.uiLanguage,
        ...(state.isTemporaryChat
          ? {}
          : { sessionId: state.sessionId, activeSessionTitle: state.activeSessionTitle }),
      }),
    }
  )
);
