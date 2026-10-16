import { FILE_SLIDE, GENERATE_SLIDE, INPUTS_SLIDE } from "@/components/guide/tours/documents";
import type { Slide } from "@/components/guide/GuideTour";

export { DOCUMENTS_TOUR } from "@/components/guide/tours/documents";
export { COMPANIES_TOUR } from "@/components/guide/tours/companies";
export { ADMIN_TOUR, TEAM_TOUR } from "@/components/guide/tours/manage";

/** Opened from a quarter's panel: the last steps of the Documents tour. */
export const QUARTER_TOUR: Slide[] = [INPUTS_SLIDE, GENERATE_SLIDE, FILE_SLIDE];
