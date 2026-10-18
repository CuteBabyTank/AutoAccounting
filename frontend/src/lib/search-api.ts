import api from "@/lib/api";
import type { SearchParams, SearchResponse } from "@/types/search";

export const searchApi = {
  search: (params: SearchParams, signal?: AbortSignal) =>
    api.get<SearchResponse>("/accounting/search", { params, signal }).then((r) => r.data),
};
