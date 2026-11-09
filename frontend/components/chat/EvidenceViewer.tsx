"use client";

import { useState } from "react";
import { Download, Eye, Layers, Maximize2, X, ZoomIn, ZoomOut, RotateCcw, MapPin, Check } from "lucide-react";
import { evidenceImageUrl, reportGeoJsonUrl, reportPdfUrl } from "@/lib/api";
import { useAppStore } from "@/lib/store";
import type { Evidence, EvidenceData } from "@/lib/types";
import { cn } from "@/lib/utils";

interface EvidenceViewerProps {
  evidence: Evidence[] | EvidenceData;
  executionId?: string;
  onOpenModal?: (title: string, image: string, metrics?: { label: string; value: string }[]) => void;
}

export function EvidenceViewer({ evidence, executionId, onOpenModal }: EvidenceViewerProps) {
  const [fullscreenImage, setFullscreenImage] = useState<{ url: string; label: string } | null>(null);
  const [showBoundingBoxes, setShowBoundingBoxes] = useState(true);
  const [showMask, setShowMask] = useState(false);
  const [zoomLevel, setZoomLevel] = useState(1);
  const [downloaded, setDownloaded] = useState(false);
  const setEvidenceModalData = useAppStore((s) => s.setEvidenceModalData);

  if (!evidence) return null;

  // Handler if evidence is EvidenceData (Object)
  if (!Array.isArray(evidence)) {
    const evData = evidence as EvidenceData;
    const currentImage = showMask && evData.changeMask ? evData.changeMask : evData.sourceImage;

    const handleDownload = () => {
      setDownloaded(true);
      const a = document.createElement("a");
      a.href = currentImage;
      a.download = "spatial_evidence.png";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      setTimeout(() => setDownloaded(false), 2000);
    };

    const handleExpand = () => {
      if (onOpenModal) {
        onOpenModal("Spatial Evidence & Grounding", currentImage, evData.metrics);
      } else {
        setEvidenceModalData({
          title: "Spatial Evidence & Grounding",
          image: currentImage,
          metrics: evData.metrics,
        });
      }
    };

    return (
      <div className="w-full rounded-2xl border border-[#262626] bg-[#0f0f0f] p-4 space-y-3.5 shadow-card">
        {/* Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pb-2 border-b border-[#1f1f1f]">
          <div className="space-y-0.5">
            <div className="flex items-center gap-2">
              <Layers className="w-4 h-4 text-[#888888]" />
              <h4 className="text-xs font-semibold text-white uppercase tracking-wider font-mono">
                Spatial Evidence & Grounding
              </h4>
            </div>
            {evData.aoi && (
              <p className="text-[11px] text-[#737373] flex items-center gap-1.5 font-mono">
                <MapPin className="w-3 h-3 text-[#525252]" />
                <span>{evData.aoi.name}</span>
                <span>•</span>
                <span>{evData.aoi.coordinates}</span>
              </p>
            )}
          </div>

          {/* Action Controls */}
          <div className="flex items-center gap-1.5 self-start sm:self-auto">
            {evData.boundingBoxes && evData.boundingBoxes.length > 0 && (
              <button
                type="button"
                onClick={() => setShowBoundingBoxes((prev) => !prev)}
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors",
                  showBoundingBoxes
                    ? "bg-[#212121] text-white border-[#333333]"
                    : "bg-transparent text-[#737373] border-transparent hover:text-white"
                )}
              >
                <Eye className="w-3 h-3" />
                <span>Bounding Boxes ({evData.boundingBoxes.length})</span>
              </button>
            )}

            {evData.changeMask && (
              <button
                type="button"
                onClick={() => setShowMask((prev) => !prev)}
                className={cn(
                  "flex items-center gap-1 px-2.5 py-1 rounded-lg text-[11px] font-medium border transition-colors",
                  showMask
                    ? "bg-[#212121] text-white border-[#333333]"
                    : "bg-transparent text-[#737373] border-transparent hover:text-white"
                )}
              >
                <span>Mask Overlay</span>
              </button>
            )}

            <div className="h-4 w-[1px] bg-[#262626] mx-0.5 hidden sm:block" />

            <button
              type="button"
              onClick={() => setZoomLevel((prev) => Math.min(prev + 0.25, 2.5))}
              className="p-1.5 rounded-lg text-[#737373] hover:text-white hover:bg-[#1a1a1a] transition-colors"
              title="Zoom in"
            >
              <ZoomIn className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setZoomLevel((prev) => Math.max(prev - 0.25, 0.75))}
              className="p-1.5 rounded-lg text-[#737373] hover:text-white hover:bg-[#1a1a1a] transition-colors"
              title="Zoom out"
            >
              <ZoomOut className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => setZoomLevel(1)}
              className="p-1.5 rounded-lg text-[#737373] hover:text-white hover:bg-[#1a1a1a] transition-colors"
              title="Reset Zoom"
            >
              <RotateCcw className="w-3.5 h-3.5" />
            </button>

            <button
              type="button"
              onClick={handleExpand}
              className="p-1.5 rounded-lg text-[#737373] hover:text-white hover:bg-[#1a1a1a] transition-colors"
              title="Open full viewer"
            >
              <Maximize2 className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* Visual Viewport */}
        <div className="relative w-full aspect-[4/3] sm:aspect-[16/10] bg-[#050505] rounded-xl overflow-hidden border border-[#212121] select-none">
          <div
            className="w-full h-full flex items-center justify-center transition-transform duration-200"
            style={{ transform: `scale(${zoomLevel})` }}
          >
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={currentImage}
              alt="Spatial Evidence Scene"
              className="w-full h-full object-cover"
            />
          </div>

          {/* Bounding Box Overlays */}
          {showBoundingBoxes && evData.boundingBoxes && (
            <div className="absolute inset-0 pointer-events-none">
              {evData.boundingBoxes.map((b) => (
                <div
                  key={b.id}
                  className="absolute border border-white/80 bg-white/10 rounded-sm"
                  style={{
                    top: `${b.coordinates[0]}%`,
                    left: `${b.coordinates[1]}%`,
                    height: `${b.coordinates[2] - b.coordinates[0]}%`,
                    width: `${b.coordinates[3] - b.coordinates[1]}%`,
                  }}
                >
                  <span className="absolute -top-5 left-0 px-1.5 py-0.5 rounded bg-black/90 border border-white/20 text-[9px] font-mono text-white whitespace-nowrap">
                    {b.label} ({(b.confidence * 100).toFixed(0)}%)
                  </span>
                </div>
              ))}
            </div>
          )}

          {/* Quick Action Footer Overlay */}
          <div className="absolute bottom-3 right-3 flex items-center gap-1.5">
            <button
              type="button"
              onClick={handleDownload}
              className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-black/80 border border-white/20 text-white text-[11px] font-medium hover:bg-black transition-colors"
            >
              {downloaded ? <Check className="w-3 h-3 text-white" /> : <Download className="w-3 h-3" />}
              <span>{downloaded ? "Saved" : "Export"}</span>
            </button>
          </div>
        </div>

        {/* Metrics Row */}
        {evData.metrics && evData.metrics.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-1">
            {evData.metrics.map((m, idx) => (
              <div
                key={idx}
                className="p-2 bg-[#141414] border border-[#212121] rounded-lg text-xs space-y-0.5"
              >
                <span className="text-[10px] text-[#737373] uppercase font-mono block truncate">
                  {m.label}
                </span>
                <p className="font-mono font-medium text-white text-sm">{m.value}</p>
                {m.change && (
                  <span className="text-[10px] text-[#888888] font-mono">
                    {m.change}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    );
  }

  // Handler if evidence is Evidence[] (Array)
  const evidenceList = evidence as Evidence[];
  if (evidenceList.length === 0) return null;

  function handleDownloadGeoJson(e: React.MouseEvent) {
    const geoFeatures = evidenceList
      .filter((ev) => ev.geo_geometry)
      .map((ev) => ({
        type: "Feature",
        geometry: ev.geo_geometry,
        properties: {
          kind: ev.type,
          label: ev.label,
          score: ev.score,
          area_m2: ev.area_m2,
          area_percentage: ev.area_percentage,
        },
      }));

    if (geoFeatures.length > 0) {
      e.preventDefault();
      const featureCollection = {
        type: "FeatureCollection",
        features: geoFeatures,
        crs: { type: "name", properties: { name: "urn:ogc:def:crs:OGC:1.3:CRS84" } },
      };
      const blob = new Blob([JSON.stringify(featureCollection, null, 2)], {
        type: "application/geo+json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `satquery_${(executionId || "export").substring(0, 12)}.geojson`;
      a.click();
      URL.revokeObjectURL(url);
    }
  }

  return (
    <div className="space-y-3 pt-2">
      <div className="flex items-center justify-between text-xs font-mono text-neutral-400">
        <div className="flex items-center gap-2">
          <Layers className="h-3.5 w-3.5 text-neutral-400" />
          <span className="uppercase tracking-wider">Grounding & Evidence ({evidenceList.length})</span>
        </div>
        {executionId && (
          <div className="flex items-center gap-3">
            <a
              href={reportPdfUrl(executionId)}
              target="_blank"
              rel="noreferrer"
              className="hover:text-white transition-colors flex items-center gap-1 cursor-pointer"
            >
              <span>PDF Dossier</span>
              <Download className="h-3 w-3" />
            </a>
            <span>•</span>
            <a
              href={reportGeoJsonUrl(executionId)}
              onClick={handleDownloadGeoJson}
              target="_blank"
              rel="noreferrer"
              className="hover:text-white transition-colors flex items-center gap-1 cursor-pointer"
            >
              <span>GeoJSON</span>
              <Download className="h-3 w-3" />
            </a>
          </div>
        )}
      </div>

      {/* Grid of Evidence Items */}
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {evidenceList.map((ev, i) => {
          const imgUrl = ev.storage_key ? evidenceImageUrl(ev.storage_key) : null;
          const displayLabel = ev.label ?? ev.type;

          return (
            <div
              key={i}
              className="rounded-xl border border-white/10 bg-[#0a0a0a] p-3 flex flex-col justify-between group"
            >
              {imgUrl ? (
                <div className="relative h-44 w-full rounded-lg bg-neutral-900 border border-white/5 overflow-hidden flex items-center justify-center">
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    src={imgUrl}
                    alt={displayLabel}
                    className="h-full w-full object-cover transition-transform duration-300 group-hover:scale-105"
                    onError={(e) => {
                      (e.target as HTMLElement).style.display = "none";
                    }}
                  />
                  <button
                    type="button"
                    onClick={() => setFullscreenImage({ url: imgUrl, label: displayLabel })}
                    className="absolute top-2 right-2 rounded-lg bg-black/60 p-1.5 text-white opacity-0 group-hover:opacity-100 transition-opacity backdrop-blur-sm"
                    aria-label="View Fullscreen"
                  >
                    <Maximize2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ) : (
                <div className="h-44 w-full rounded-lg bg-tech-grid border border-white/5 flex flex-col items-center justify-center p-4 text-center font-mono text-xs text-neutral-400">
                  <span className="uppercase text-[10px] text-neutral-400 tracking-wider">Spatial Vector</span>
                  <span className="text-white mt-1 font-medium">{displayLabel}</span>
                  {ev.area_m2 != null && (
                    <span className="text-emerald-400 text-[11px] mt-1">
                      {ev.area_m2.toLocaleString()} m² ({ev.area_percentage?.toFixed(1)}%)
                    </span>
                  )}
                </div>
              )}

              <div className="mt-2.5 flex items-center justify-between font-mono text-[11px]">
                <span className="text-neutral-300 truncate">{displayLabel}</span>
                {/* This number is the fraction of image pixels the detector
                    matched for this label -- it is coverage, NOT accuracy or
                    confidence. Labelling it "score" read as an accuracy claim. */}
                {ev.score != null && (
                  <span
                    className="text-neutral-400"
                    title="Share of the image matched for this label. This is coverage, not accuracy or confidence."
                  >
                    {(ev.score * 100).toFixed(0)}% of image
                  </span>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Fullscreen modal fallback */}
      {fullscreenImage && (
        <div
          onClick={() => setFullscreenImage(null)}
          className="fixed inset-0 z-50 flex items-center justify-center bg-black/80 backdrop-blur-md p-4 animate-fade-in"
        >
          <div
            onClick={(e) => e.stopPropagation()}
            className="relative max-h-[90vh] max-w-[90vw] overflow-hidden rounded-2xl border border-white/20 bg-black p-2 shadow-2xl"
          >
            <button
              type="button"
              onClick={() => setFullscreenImage(null)}
              className="absolute top-4 right-4 z-10 rounded-full bg-black/60 p-2 text-white hover:bg-white/20 transition-colors"
            >
              <X className="h-4 w-4" />
            </button>
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={fullscreenImage.url}
              alt={fullscreenImage.label}
              className="max-h-[85vh] max-w-full rounded-xl object-contain"
            />
            <div className="p-3 text-center font-mono text-xs text-neutral-300">
              {fullscreenImage.label}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
