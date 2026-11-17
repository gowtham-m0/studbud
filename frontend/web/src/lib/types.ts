export interface User {
  id: string;
  display_name: string;
  status: "active" | "disabled";
  created_at: string;
}

export interface SessionInfo {
  user: User;
  session_expires_at: string;
  key_expires_at: string;
}

export type DocumentStatus =
  | "uploaded"
  | "queued"
  | "processing"
  | "ready"
  | "failed"
  | "needs_ocr";

export interface DocumentItem {
  id: string;
  user_id: string;
  file_name: string;
  file_size_bytes: number;
  page_count: number | null;
  status: DocumentStatus;
  failure_reason: string | null;
  created_at: string;
  processed_at: string | null;
}

export interface UploadResponse {
  document_id: string;
  status: DocumentStatus;
  message: string;
}

export interface SearchResult {
  chunk_id: string;
  document_id: string;
  document_name: string;
  section_title: string | null;
  page_start: number;
  page_end: number;
  snippet: string;
  score: number;
}

export interface SearchResponse {
  query: string;
  results: SearchResult[];
}

export interface Citation {
  chunk_id: string;
  document_id: string;
  document_name: string;
  page_start: number;
  page_end: number;
  excerpt: string;
}

export interface Explanation {
  explanation_id: string;
  document_id: string;
  document_name: string;
  section_title: string | null;
  page_start: number;
  page_end: number;
  answer: string;
  citations: Citation[];
  insufficient_context: boolean;
  model: string;
}

export interface DocumentAsset {
  id: string;
  page_number: number;
  kind: "page" | "figure";
  asset_index: number;
  mime_type: string;
  width: number;
  height: number;
  caption: string | null;
  content_path: string;
}
