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

export type AnalysisRunStatus = "PENDING" | "RUNNING" | "COMPLETED" | "FAILED";
export type AnalysisStage =
  | "QUEUED"
  | "PARSE_DOCUMENTS"
  | "BUILD_INTERVIEW_MAP"
  | "COMPLETED"
  | "FAILED";
export type RiskCategory =
  | "TECHNICAL_UNDERSTANDING"
  | "OWNERSHIP"
  | "EVIDENCE_GAP"
  | "CONSISTENCY"
  | "MOTIVATION_DEPTH";
export type VerificationStatus =
  | "UNVERIFIED"
  | "PARTIALLY_VERIFIED"
  | "VERIFIED"
  | "CONFIRMED_RISK";
export type SuggestedQuestionType =
  | "EVIDENCE_PROBE"
  | "OWNERSHIP_PROBE"
  | "TECHNICAL_DEPTH_PROBE"
  | "CONSISTENCY_PROBE"
  | "MOTIVATION_PROBE"
  | "TRADEOFF_PROBE"
  | "REFLECTION_PROBE";

export interface SourceLocation {
  page_number: number;
  section: string | null;
  start_offset: number | null;
  end_offset: number | null;
}

export interface Evidence {
  evidence_id: string;
  source_type: "APPLICATION_DOCUMENT";
  document_id: string;
  document_type: DocumentType;
  location: SourceLocation;
  original_text: string;
}

export interface CandidateClaim {
  claim_id: string;
  category: string;
  statement: string;
  assertion_strength: string;
  evidence_ids: string[];
  interview_value: "HIGH";
}

export interface CoverageCondition {
  condition_id: string;
  type: string;
  description: string;
  required: boolean;
}

export interface VerificationObjective {
  objective_id: string;
  risk_id: string;
  target_claim_id: string;
  verification_goal: string;
  coverage_conditions: CoverageCondition[];
}

export interface InterviewRisk {
  risk_id: string;
  category: RiskCategory;
  severity: number;
  title: string;
  evidence_ids: string[];
  claim_id: string;
  reason: string;
  objectives: VerificationObjective[];
  suggested_question_types: SuggestedQuestionType[];
  max_followups: number;
  verification_status: VerificationStatus;
}

export interface CandidateProfile {
  overview: string;
  research_interests: string[];
  high_value_claim_ids: string[];
  missing_or_uncertain_information: string[];
}

export interface InputDocumentManifest {
  document_id: string;
  document_type: DocumentType;
  sha256: string;
  page_count: number;
}

export interface InterviewMap {
  schema_version: "interview-map-v1";
  analysis_run_id: string;
  input_manifest: InputDocumentManifest[];
  candidate_profile: CandidateProfile;
  evidence: Evidence[];
  claims: CandidateClaim[];
  risks: InterviewRisk[];
  priority_risk_ids: string[];
}

export interface AnalysisRunResponse {
  id: string;
  application_id: string;
  status: AnalysisRunStatus;
  stage: AnalysisStage;
  error_code: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  interview_map: InterviewMap | null;
}
