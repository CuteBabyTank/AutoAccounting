"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Camera, CircleNotch, ImageSquare, X } from "@phosphor-icons/react";
import { useAuth } from "@/lib/auth";

type Step = "choose" | "camera" | "review";

const MAX_BYTES = 5 * 1024 * 1024;

/** Why a picked file can't be used, or null. Some browsers leave `type` empty, so fall back to the extension. */
function fileProblem(file: File): string | null {
  const ok = ["image/jpeg", "image/png"].includes(file.type) || (!file.type && /\.(jpe?g|png)$/i.test(file.name));
  if (!ok) return "That file isn't a JPG or PNG. Pick a JPG or PNG photo.";
  if (file.size >= MAX_BYTES) return `That photo is ${(file.size / 1024 / 1024).toFixed(1)} MB. Pick one under 5 MB.`;
  return null;
}

/** Profile-picture dialog: upload a file, or take one. Phones use the native camera (`capture`); elsewhere a
 *  webcam preview is shown and a square frame is captured. Stays open (with any error) until the upload lands. */
export default function AvatarPicker({ onClose }: { onClose: () => void }) {
  const { uploadAvatar } = useAuth();
  const [step, setStep] = useState<Step>("choose");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [shot, setShot] = useState<{ file: File; url: string } | null>(null);
  // Phones take the picture with their own camera app; elsewhere we show a webcam preview.
  const [nativeCamera] = useState(
    () => window.matchMedia("(pointer: coarse)").matches || !navigator.mediaDevices?.getUserMedia,
  );
  const video = useRef<HTMLVideoElement>(null);
  const stream = useRef<MediaStream | null>(null);

  const stopCamera = () => {
    stream.current?.getTracks().forEach((t) => t.stop());
    stream.current = null;
  };

  useEffect(() => stopCamera, []);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  useEffect(() => () => { if (shot) URL.revokeObjectURL(shot.url); }, [shot]);

  const choose = async (file: File | undefined) => {
    if (!file || saving) return;
    const problem = fileProblem(file);
    if (problem) {
      setError(problem);
      setStep("choose");
      return;
    }
    setError(null);
    setSaving(true);
    try {
      await uploadAvatar(file);
      onClose();
    } catch (err) {
      const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail;
      setError(typeof detail === "string" ? detail : "Upload failed. Check your connection and try again.");
      setStep("choose");
    } finally {
      setSaving(false);
    }
  };

  // Clear the input after reading it, so picking the same file again still fires `change`.
  const onPicked = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = "";
    choose(file);
  };

  const startCamera = async () => {
    setError(null);
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: "user", width: { ideal: 1280 }, height: { ideal: 720 } },
        audio: false,
      });
      setStep("camera");
    } catch {
      setError("Camera unavailable. Allow camera access in your browser, or upload a photo instead.");
    }
  };

  // Attach the stream once the <video> for the camera step has mounted.
  useEffect(() => {
    if (step === "camera" && video.current && stream.current) video.current.srcObject = stream.current;
  }, [step]);

  const capture = () => {
    const v = video.current;
    if (!v || !v.videoWidth) return;
    const side = Math.min(v.videoWidth, v.videoHeight);
    const out = Math.min(side, 768);
    const canvas = document.createElement("canvas");
    canvas.width = canvas.height = out;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    // Mirrored, like the preview, so the picture matches what the person saw.
    ctx.translate(out, 0);
    ctx.scale(-1, 1);
    ctx.drawImage(v, (v.videoWidth - side) / 2, (v.videoHeight - side) / 2, side, side, 0, 0, out, out);
    canvas.toBlob(
      (blob) => {
        if (!blob) return;
        const file = new File([blob], "camera.jpg", { type: "image/jpeg" });
        setShot({ file, url: URL.createObjectURL(blob) });
        setStep("review");
      },
      "image/jpeg",
      0.9,
    );
  };

  const optionClass =
    "relative flex items-center gap-3 w-full px-4 py-3 rounded-xl border border-[var(--border)] text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-primary)] transition-colors";
  const secondaryClass =
    "px-4 py-2 rounded-lg border border-[var(--border)] text-sm font-medium text-[var(--text-primary)] hover:bg-[var(--bg-primary)] transition-colors";
  const primaryClass =
    "px-4 py-2 rounded-lg bg-[var(--accent)] text-white text-sm font-medium hover:opacity-90 transition-opacity";

  return createPortal(
    <div
      className="lp-skin overlay-enter fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="avatar-picker-title"
        className="modal-enter bg-[var(--bg-secondary)] rounded-xl border border-[var(--border)] p-6 w-full max-w-sm shadow-xl"
      >
        <div className="flex items-center justify-between mb-4">
          <h3 id="avatar-picker-title" className="text-lg font-semibold text-[var(--text-primary)]">
            Profile picture
          </h3>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="p-1.5 -mr-1.5 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--bg-primary)]"
          >
            <X size={18} />
          </button>
        </div>

        {step === "choose" && (
          <div className="flex flex-col gap-2">
            {/* Real <label>s around the file inputs: browsers (Safari especially) won't open a picker from a
                script .click() on a hidden input. */}
            <label className={`${optionClass} cursor-pointer focus-within:ring-2 focus-within:ring-[var(--accent)]`}>
              <input type="file" accept="image/jpeg,image/png" autoFocus className="sr-only" onChange={onPicked} />
              <ImageSquare size={20} className="text-[var(--accent)]" />
              Upload photo
            </label>
            {nativeCamera ? (
              <label className={`${optionClass} cursor-pointer focus-within:ring-2 focus-within:ring-[var(--accent)]`}>
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  capture="user"
                  className="sr-only"
                  onChange={onPicked}
                />
                <Camera size={20} className="text-[var(--accent)]" />
                Take picture
              </label>
            ) : (
              <button type="button" onClick={startCamera} className={optionClass}>
                <Camera size={20} className="text-[var(--accent)]" />
                Take picture
              </button>
            )}
            {saving ? (
              <p className="mt-1 flex items-center gap-1.5 text-xs text-[var(--text-secondary)]">
                <CircleNotch size={12} className="animate-spin" /> Uploading…
              </p>
            ) : (
              <p className="mt-1 text-xs text-[var(--text-secondary)]">JPG or PNG, under 5 MB.</p>
            )}
            {error && (
              <p role="alert" className="text-xs text-[var(--error)]">
                {error}
              </p>
            )}
          </div>
        )}

        {step === "camera" && (
          <>
            <div className="aspect-square w-full overflow-hidden rounded-xl bg-black">
              <video ref={video} autoPlay playsInline muted className="w-full h-full object-cover -scale-x-100" />
            </div>
            <div className="flex items-center gap-3 justify-end mt-4">
              <button type="button" onClick={() => { stopCamera(); setStep("choose"); }} className={secondaryClass}>
                Back
              </button>
              <button type="button" autoFocus onClick={capture} className={primaryClass}>
                Capture
              </button>
            </div>
          </>
        )}

        {step === "review" && shot && (
          <>
            {/* eslint-disable-next-line @next/next/no-img-element -- local blob: preview */}
            <img src={shot.url} alt="Captured photo" className="aspect-square w-full rounded-xl object-cover" />
            <div className="flex items-center gap-3 justify-end mt-4">
              <button type="button" onClick={() => { setShot(null); setStep("camera"); }} className={secondaryClass}>
                Retake
              </button>
              <button type="button" autoFocus onClick={() => choose(shot.file)} disabled={saving} className={primaryClass}>
                {saving ? "Uploading…" : "Use photo"}
              </button>
            </div>
          </>
        )}

      </div>
    </div>,
    document.body,
  );
}
