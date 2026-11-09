"use client";

import { useEffect, useState } from "react";
import { Cpu, Server, Check, X, ExternalLink, Zap } from "lucide-react";
import { DEFAULT_RENDER_URL, getEffectiveApiUrl, setCustomGpuUrl } from "@/lib/api";
import { useTheme } from "@/lib/theme";

interface GpuNodeModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export function GpuNodeModal({ isOpen, onClose }: GpuNodeModalProps) {
  const { resolvedTheme } = useTheme();
  const isLight = resolvedTheme === "light";
  const [gpuUrl, setGpuUrl] = useState("");
  const [currentActive, setCurrentActive] = useState("");
  const [isSaved, setIsSaved] = useState(false);

  useEffect(() => {
    if (typeof window !== "undefined") {
      const saved = localStorage.getItem("satquery_custom_gpu_url") || "";
      setGpuUrl(saved);
      setCurrentActive(getEffectiveApiUrl());
    }
  }, [isOpen]);

  if (!isOpen) return null;

  function handleSave() {
    setCustomGpuUrl(gpuUrl);
    setIsSaved(true);
    setCurrentActive(getEffectiveApiUrl());
    setTimeout(() => {
      setIsSaved(false);
      onClose();
      // Reload page to re-initialize sessions with new backend
      window.location.reload();
    }, 600);
  }

  function handleReset() {
    setCustomGpuUrl(null);
    setGpuUrl("");
    setCurrentActive(DEFAULT_RENDER_URL);
    setIsSaved(true);
    setTimeout(() => {
      setIsSaved(false);
      onClose();
      window.location.reload();
    }, 600);
  }

  const isGpuActive = currentActive !== DEFAULT_RENDER_URL;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-fade-in">
      <div
        className={`w-full max-w-md rounded-2xl border p-6 shadow-2xl transition-all ${
          isLight
            ? "bg-[#fcfbf9] border-black/10 text-neutral-900"
            : "bg-[#111111] border-white/10 text-white"
        }`}
      >
        <div className="flex items-center justify-between pb-4 border-b border-white/10">
          <div className="flex items-center gap-2">
            <Cpu className="w-5 h-5 text-emerald-400" />
            <h3 className="font-semibold text-base">Backend Dual-Mode</h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-white/10 text-neutral-400 hover:text-white transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>

        <div className="py-4 space-y-4 text-xs">
          {/* Active Status Badge */}
          <div
            className={`p-3 rounded-xl border flex items-center justify-between ${
              isGpuActive
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-400"
                : isLight
                ? "bg-black/5 border-black/10 text-neutral-700"
                : "bg-white/5 border-white/10 text-neutral-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <span
                className={`w-2 h-2 rounded-full ${
                  isGpuActive ? "bg-emerald-400 animate-pulse" : "bg-blue-400"
                }`}
              />
              <span className="font-medium">
                {isGpuActive ? "Active: Kaggle GPU Node" : "Active: Render Cloud 24/7"}
              </span>
            </div>
            <span className="text-[10px] font-mono opacity-70">
              {isGpuActive ? "T4 GPU (16GB)" : "Continuous CPU"}
            </span>
          </div>

          <div>
            <label className="block font-medium mb-1.5 text-neutral-300">
              Kaggle / Cloudflare Tunnel URL:
            </label>
            <input
              type="text"
              placeholder="https://xxxx.trycloudflare.com"
              value={gpuUrl}
              onChange={(e) => setGpuUrl(e.target.value)}
              className={`w-full px-3 py-2 rounded-xl border text-xs font-mono outline-none transition-all ${
                isLight
                  ? "bg-white border-black/15 text-neutral-900 focus:border-black"
                  : "bg-[#181818] border-white/15 text-white focus:border-emerald-500"
              }`}
            />
            <p className="text-[11px] text-neutral-400 mt-1">
              Paste the URL generated from Cell 5 in your Kaggle notebook.
            </p>
          </div>

          <div className="p-2.5 rounded-lg bg-neutral-900/60 border border-white/5 text-[11px] text-neutral-400 space-y-1">
            <div className="flex items-center gap-1.5 text-neutral-200 font-medium">
              <Zap className="w-3.5 h-3.5 text-amber-400" />
              <span>Automatic Failover Built-in:</span>
            </div>
            <p>
              When your Kaggle GPU is online, queries run on the neural network. If your Kaggle
              notebook stops, the app automatically switches to Render with zero errors!
            </p>
          </div>
        </div>

        <div className="flex items-center justify-between pt-3 border-t border-white/10 gap-2">
          <button
            type="button"
            onClick={handleReset}
            className="px-3 py-2 rounded-xl text-xs font-medium text-neutral-400 hover:text-white transition-colors"
          >
            Reset to Render
          </button>

          <div className="flex items-center gap-2">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-xl text-xs font-medium border border-white/10 hover:bg-white/5 transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              className="px-4 py-2 rounded-xl text-xs font-medium bg-emerald-500 hover:bg-emerald-600 text-black font-semibold transition-colors flex items-center gap-1.5"
            >
              {isSaved ? <Check className="w-3.5 h-3.5" /> : null}
              <span>{isSaved ? "Connected!" : "Save & Connect"}</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
