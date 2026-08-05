export type DocumentType = "CV" | "PS";
export type ParseStatus = "UPLOADED" | "PARSING" | "PARSED" | "FAILED";

export interface DocumentResponse {
  id: string;
  application_id: string;
  document_type: DocumentType;
  original_filename: string;
  mime_type: string;
  size_bytes: number;
  parse_status: ParseStatus;
  created_at: string;
}

export interface ApplicationSummary {
  id: string;
  target_school: string;
  target_program: string;
  degree_type: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export type ApplicationResponse = ApplicationSummary;

export interface ApplicationDetail extends ApplicationSummary {
  documents: DocumentResponse[];
}

export interface ApplicationList {
  items: ApplicationSummary[];
}
