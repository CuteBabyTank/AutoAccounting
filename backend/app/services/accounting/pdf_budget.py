"""Process-wide admission for disposable PDF children, shared by every PDF pool."""

from threading import BoundedSemaphore

# Cloud Run has 4096 MiB (cloudbuild.yaml). Three 768 MiB address-space caps leave
# 1792 MiB explicitly reserved for the parent, extraction chunks, caches and uploads.
# Keep 768 MiB per child: rendering/encoding MAX_RENDER_PIXELS does not fit in 512 MiB.
PDF_MEMORY_BYTES = 768 * 1024 * 1024
PARENT_HEADROOM_BYTES = 1792 * 1024 * 1024
PDF_CHILD_SLOTS = BoundedSemaphore(3)
# Background work (upload compression, extraction/detection renders) may hold at most two of the
# three children, so an interactive page view always has one. Background callers take this permit
# first (blocking) and then a PDF_CHILD_SLOTS permit; viewers take only PDF_CHILD_SLOTS. The total
# never exceeds the three children above, so the 4 GiB budget is unchanged.
BACKGROUND_CHILD_SLOTS = BoundedSemaphore(2)
