"use client";

import { useState } from "react";
import GuideTour, { type Slide } from "@/components/guide/GuideTour";
import SpotlightTour, { type Spot } from "@/components/guide/SpotlightTour";

interface Props {
  open: boolean;
  onClose: () => void;
  label: string;
  spots: Spot[];
  slides: Slide[];
}

/** A page's guide: the on-screen tour first, with the illustrated walkthrough offered at its end. */
export default function PageGuide({ open, onClose, label, spots, slides }: Props) {
  const [illustrated, setIllustrated] = useState(false);
  return (
    <>
      <SpotlightTour open={open} onClose={onClose} label={label} spots={spots} onMore={() => setIllustrated(true)} />
      <GuideTour open={illustrated} onClose={() => setIllustrated(false)} label={label} slides={slides} />
    </>
  );
}
