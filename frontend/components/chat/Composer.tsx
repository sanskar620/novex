"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, Image as ImageIcon, Layers, Mic, Paperclip, Plus, Radio, X } from "lucide-react";
import { useT } from "@/lib/i18n";
import { useAppStore } from "@/lib/store";
import { SATELLITE_IMAGES } from "@/lib/satellite-assets";
import { Attachment, SensorType } from "@/lib/types";
import { AttachmentChip } from "./AttachmentChip";
import { cn } from "@/lib/utils";
import { useTheme } from "@/lib/theme";

interface ComposerProps {
  onSend: (text: string, attachments?: Attachment[]) => void;
  onUploadFiles?: (files: File[]) => void;
  isLoading: boolean;
  placeholder?: string;
  isCentered?: boolean;
  initialText?: string;
  initialAttachments?: Attachment[];
}

export function Composer({
  onSend,
  onUploadFiles,
  isLoading,
  placeholder,
  isCentered = false,
  initialText = "",
  initialAttachments = [],
}: ComposerProps) {
  const [text, setText] = useState(initialText);
  const [isListening, setIsListening] = useState(false);
  const [dragActive, setDragActive] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const recognitionRef = useRef<any>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const pendingAttachments = useAppStore((s) => s.pendingAttachments);
  const addPendingAttachment = useAppStore((s) => s.addPendingAttachment);
  const removePendingAttachment = useAppStore((s) => s.removePendingAttachment);
  const { t } = useT();
  const { resolvedTheme } = useTheme();
  const isLight = resolvedTheme === "light";

  useEffect(() => {
    if (initialText) setText(initialText);
  }, [initialText]);

  useEffect(() => {
    if (initialAttachments && initialAttachments.length > 0) {
      initialAttachments.forEach((att) => {
        addPendingAttachment({
          id: att.id,
          name: att.name,
          previewUrl: att.url,
          type: "optical",
          sensor: typeof att.sensor === "string" ? att.sensor : undefined,
          resolution: att.resolution,
        });
      });
    }
  }, [initialAttachments, addPendingAttachment]);

  useEffect(() => {
    function handleClickOutside(event: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(event.target as Node)) {
        setMenuOpen(false);
      }
    }
    if (menuOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [menuOpen]);

  function toggleVoiceInput() {
    if (isListening) {
      if (recognitionRef.current) {
        recognitionRef.current.stop();
      }
      setIsListening(false);
      return;
    }

    const SpeechRec =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;

    if (!SpeechRec) {
      setText((prev) =>
        prev
          ? `${prev} Analyze flood extent using Sentinel-1 SAR imagery.`
          : "Analyze flood extent using Sentinel-1 SAR imagery."
      );
      return;
    }

    try {
      const recognition = new SpeechRec();
      recognition.continuous = false;
      recognition.interimResults = true;
      recognition.lang = "en-US";

      recognition.onstart = () => {
        setIsListening(true);
      };

      recognition.onresult = (event: any) => {
        const transcript = Array.from(event.results)
          .map((res: any) => res[0].transcript)
          .join("");
        setText(transcript);
      };

      recognition.onerror = () => {
        setIsListening(false);
      };

      recognition.onend = () => {
        setIsListening(false);
      };

      recognitionRef.current = recognition;
      recognition.start();
    } catch {
      setIsListening(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleSend() {
    if ((!text.trim() && pendingAttachments.length === 0) || isLoading) return;

    const mappedAttachments: Attachment[] = pendingAttachments.map((p) => ({
      id: p.id,
      name: p.name,
      size: p.sizeBytes ? `${(p.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "14.2 MB",
      type: "image/geotiff",
      url: p.previewUrl,
      sensor: p.sensor,
      resolution: p.resolution,
    }));

    onSend(text, mappedAttachments);
    setText("");
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const files = e.target.files;
    if (!files || files.length === 0) return;

    if (onUploadFiles) {
      onUploadFiles(Array.from(files));
    } else {
      Array.from(files).forEach((file, idx) => {
        addPendingAttachment({
          id: `upload-${Date.now()}-${idx}`,
          file,
          previewUrl: URL.createObjectURL(file),
          name: file.name,
          sizeBytes: file.size,
          type: "optical",
          sensor: "Custom GeoTIFF",
          resolution: "10m",
        });
      });
    }
    setMenuOpen(false);
    if (fileInputRef.current) fileInputRef.current.value = "";
  }

  async function handleAddPreset(sensor: string, name: string, url: string) {
    setMenuOpen(false);
    try {
      const res = await fetch(url);
      const blob = await res.blob();
      const isSar = sensor.includes("SAR");
      const file = new File([blob], name, { type: "image/jpeg" });
      if (onUploadFiles) {
        onUploadFiles([file]);
      } else {
        addPendingAttachment({
          id: `preset-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
          file,
          previewUrl: url,
          name,
          sizeBytes: blob.size || 14 * 1024 * 1024,
          type: isSar ? "sar" : "optical",
          sensor,
          resolution: "10m",
        });
      }
    } catch {
      addPendingAttachment({
        id: `preset-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        previewUrl: url,
        name,
        sizeBytes: 14 * 1024 * 1024,
        type: sensor.includes("SAR") ? "sar" : "optical",
        sensor,
        resolution: "10m",
      });
    }
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragActive(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      if (onUploadFiles) {
        onUploadFiles(Array.from(e.dataTransfer.files));
      } else {
        Array.from(e.dataTransfer.files).forEach((file, idx) => {
          addPendingAttachment({
            id: `drop-${Date.now()}-${idx}`,
            file,
            previewUrl: URL.createObjectURL(file),
            name: file.name,
            sizeBytes: file.size,
            type: "optical",
            sensor: "Custom GeoTIFF",
            resolution: "10m",
          });
        });
      }
    }
  }

  function handleInput(e: React.ChangeEvent<HTMLTextAreaElement>) {
    setText(e.target.value);
    e.target.style.height = "auto";
    e.target.style.height = `${Math.min(e.target.scrollHeight, 180)}px`;
  }

  return (
    <div
      onDragOver={(e) => {
        e.preventDefault();
        setDragActive(true);
      }}
      onDragLeave={() => setDragActive(false)}
      onDrop={handleDrop}
      className={`w-full max-w-3xl mx-auto px-4 transition-all ${
        dragActive ? "opacity-90" : ""
      }`}
    >
      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".tif,.tiff,.geotiff,.png,.jpg,.jpeg"
        onChange={handleFileChange}
        className="hidden"
      />

      {/* Attachment Chips Preview Bar */}
      {pendingAttachments.length > 0 && (
        <div className="mb-2.5 flex flex-wrap gap-2 animate-in fade-in zoom-in-95 duration-150">
          {pendingAttachments.map((att) => (
            <AttachmentChip
              key={att.id}
              attachment={{
                id: att.id,
                name: att.name,
                size: att.sizeBytes ? `${(att.sizeBytes / (1024 * 1024)).toFixed(1)} MB` : "14.2 MB",
                type: "image/geotiff",
                url: att.previewUrl,
                sensor: att.sensor,
                resolution: att.resolution,
              }}
              onRemove={removePendingAttachment}
            />
          ))}
        </div>
      )}

      {/* Main Pill Input Bar */}
      <div
        className={cn(
          "relative flex items-center gap-3 rounded-[32px] border px-4 py-3 sm:py-3.5 shadow-2xl transition-all duration-200",
          isLight
            ? dragActive
              ? "border-black/30 bg-[#fcfbf8] shadow-[0_10px_36px_-4px_rgba(40,30,20,0.12)]"
              : "border-black/10 bg-[#fcfbf8] focus-within:border-black/25 shadow-[0_10px_36px_-4px_rgba(40,30,20,0.08)]"
            : dragActive
              ? "border-white bg-[#1a1a1a]"
              : "border-[#2e2e2e] bg-[#141414] focus-within:border-[#4d4d4d]"
        )}
      >
        {/* Attachment Dropdown Button */}
        <div className="relative shrink-0" ref={menuRef}>
          <button
            type="button"
            onClick={() => setMenuOpen((prev) => !prev)}
            className={cn(
              "flex h-9 w-9 items-center justify-center rounded-full transition-colors border",
              menuOpen || pendingAttachments.length > 0
                ? isLight
                  ? "bg-black/10 border-black/20 text-neutral-900"
                  : "bg-[#212121] border-[#383838] text-white"
                : isLight
                  ? "bg-black/[0.04] border-black/10 text-neutral-600 hover:text-black hover:bg-black/10"
                  : "bg-[#171717] border-[#262626] text-[#737373] hover:text-white hover:bg-[#1f1f1f]"
            )}
            title="Attach satellite imagery or select sensor"
          >
            <Paperclip className="h-4 w-4" />
          </button>

          {/* Quick Attachment Dropdown Menu */}
          {menuOpen && (
            <div className={`absolute bottom-full left-0 mb-2 w-64 rounded-2xl p-2 shadow-2xl z-50 space-y-1 animate-in fade-in zoom-in-95 duration-100 border ${
              isLight
                ? "bg-[#fcfbf8] border-black/10 text-neutral-800 shadow-xl"
                : "bg-[#171717] border-[#303030]"
            }`}>
              <div className={`px-2.5 py-1.5 text-[10px] uppercase font-mono tracking-wider ${
                isLight ? "text-neutral-500" : "text-[#737373]"
              }`}>
                Select Imagery Source
              </div>

              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className={`w-full flex items-center gap-2.5 px-3 py-2 text-xs rounded-xl transition-colors text-left ${
                  isLight
                    ? "text-neutral-800 hover:bg-black/5"
                    : "text-[#e5e5e5] hover:text-white hover:bg-[#262626]"
                }`}
              >
                <ImageIcon className={`w-3.5 h-3.5 ${isLight ? "text-neutral-600" : "text-[#888888]"}`} />
                <div>
                  <p className="font-medium">Upload File (GeoTIFF, PNG)</p>
                  <p className={`text-[10px] ${isLight ? "text-neutral-500" : "text-[#737373]"}`}>Single or multi-temporal raster</p>
                </div>
              </button>

              <div className={`h-[1px] my-1 ${isLight ? "bg-black/10" : "bg-[#262626]"}`} />

              <div className={`px-2.5 py-1 text-[10px] font-mono ${isLight ? "text-neutral-400" : "text-[#525252]"}`}>
                Preset Satellite Layers
              </div>

              <button
                type="button"
                onClick={() =>
                  handleAddPreset(
                    "Sentinel-2",
                    "sentinel2_pune_2025.tif",
                    SATELLITE_IMAGES.puneAfter
                  )
                }
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors text-left ${
                  isLight
                    ? "text-neutral-700 hover:text-black hover:bg-black/5"
                    : "text-[#d4d4d4] hover:text-white hover:bg-[#262626]"
                }`}
              >
                <Layers className={`w-3 h-3 ${isLight ? "text-neutral-500" : "text-[#888888]"}`} />
                <span>Sentinel-2 MSI (10m Optical)</span>
              </button>

              <button
                type="button"
                onClick={() =>
                  handleAddPreset(
                    "Sentinel-1 SAR",
                    "sentinel1_sar_c_band.tif",
                    SATELLITE_IMAGES.sarRadar
                  )
                }
                className={`w-full flex items-center gap-2 px-3 py-1.5 text-xs rounded-lg transition-colors text-left ${
                  isLight
                    ? "text-neutral-700 hover:text-black hover:bg-black/5"
                    : "text-[#d4d4d4] hover:text-white hover:bg-[#262626]"
                }`}
              >
                <Radio className={`w-3 h-3 ${isLight ? "text-neutral-500" : "text-[#888888]"}`} />
                <span>Sentinel-1 C-Band SAR (Radar)</span>
              </button>
            </div>
          )}
        </div>

        {/* Textarea Input */}
        <textarea
          ref={textareaRef}
          rows={1}
          value={text}
          onChange={handleInput}
          onKeyDown={handleKeyDown}
          placeholder={
            placeholder ??
            (isCentered ? t("composer.placeholder") : t("composer.placeholderExpanded"))
          }
          className={`flex-1 max-h-48 min-h-[28px] bg-transparent py-1 text-[15px] sm:text-[16px] focus:outline-none resize-none font-sans leading-relaxed font-normal ${
            isLight
              ? "text-[#18181b] placeholder:text-[#78716c]"
              : "text-white placeholder:text-[#525252]"
          }`}
        />

        {/* Right Action Icons: Mic, Send */}
        <div className="flex items-center gap-2 shrink-0">
          {/* Microphone Voice Icon */}
          <button
            type="button"
            onClick={toggleVoiceInput}
            className={`flex h-9 w-9 items-center justify-center rounded-full transition-colors ${
              isListening
                ? "bg-red-500/20 text-red-500 border border-red-500/30 animate-pulse shadow-[0_0_12px_rgba(239,68,68,0.3)]"
                : isLight
                  ? "text-neutral-500 hover:text-neutral-900 hover:bg-black/5"
                  : "text-neutral-400 hover:text-white hover:bg-white/10"
            }`}
            title={isListening ? "Listening... (click to stop)" : "Voice query"}
          >
            <Mic className="h-4 w-4" />
          </button>

          {/* Submit / Send Button */}
          <button
            type="button"
            onClick={handleSend}
            disabled={(!text.trim() && pendingAttachments.length === 0) || isLoading}
            className={cn(
              "w-8 h-8 rounded-xl flex items-center justify-center transition-all shrink-0",
              (text.trim() || pendingAttachments.length > 0) && !isLoading
                ? isLight
                  ? "bg-[#18181b] text-white hover:bg-[#27272a] shadow-md cursor-pointer"
                  : "bg-white text-black hover:bg-[#e5e5e5] shadow-md cursor-pointer"
                : isLight
                  ? "bg-black/10 text-neutral-400 cursor-not-allowed"
                  : "bg-[#212121] text-[#525252] cursor-not-allowed"
            )}
            aria-label="Send message"
          >
            <ArrowUp className="w-4 h-4 stroke-[2.5]" />
          </button>
        </div>
      </div>

      {/* Understated Disclaimer Text */}
      <p className={`text-[10.5px] sm:text-[11px] text-center font-mono mt-2.5 select-none ${
        isLight ? "text-[#78716c]" : "text-[#525252]"
      }`}>
        {t("composer.disclaimer")}
      </p>
    </div>
  );
}
