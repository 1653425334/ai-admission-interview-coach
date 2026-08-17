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
  program_url?: string | null;
  program_description?: string | null;
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
  relevance_to_target?: string | null;
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
  application_context?: {
    target_school: string;
    target_program: string;
    program_url: string | null;
    program_description: string | null;
  } | null;
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

export type InterviewSessionStatus = "PENDING" | "ACTIVE" | "COMPLETED" | "FAILED";
export type InterviewTurnStatus = "ASKED" | "ANSWERED" | "EVALUATED";
export type CoverageResult = "MET" | "NOT_MET" | "UNCLEAR";

export interface ConditionEvaluation {
  condition_id: string;
  result: CoverageResult;
  answer_excerpt: string | null;
  reason: string;
}

export interface CommunicationFeedback {
  grammar: string | null;
  vocabulary: string | null;
  clarity: string | null;
  structure: string | null;
  conciseness: string | null;
}

export interface AnswerEvaluation {
  question_id: string;
  risk_id: string;
  objective_id: string;
  condition_results: ConditionEvaluation[];
  unmet_required_condition_ids: string[];
  strengths: string[];
  missing_points: string[];
  unsupported_claims: string[];
  communication_feedback: CommunicationFeedback | null;
}

export interface ConditionState {
  condition_id: string;
  latest_result: CoverageResult | null;
  last_question_id: string | null;
}

export interface ObjectiveState {
  objective_id: string;
  condition_states: ConditionState[];
  followups_used: number;
  all_required_conditions_met: boolean;
  unresolved_required_condition_ids: string[];
}

export interface RiskState {
  risk_id: string;
  verification_status: VerificationStatus;
  objective_states: ObjectiveState[];
}

export interface FinalInterviewReport {
  overall_summary: string;
  strong_answers: string[];
  unresolved_risks: string[];
  preparation_recommendations: string[];
  english_communication_feedback: CommunicationFeedback | null;
}

export interface InterviewTurnResponse {
  id: string;
  sequence_number: number;
  risk_id: string;
  objective_id: string;
  question_type: SuggestedQuestionType;
  target_condition_ids: string[];
  question_text: string;
  followup_index: number;
  parent_turn_id: string | null;
  answer_text: string | null;
  status: InterviewTurnStatus;
  evaluation: AnswerEvaluation | null;
  asked_at: string;
  answered_at: string | null;
}

export interface InterviewSessionResponse {
  id: string;
  application_id: string;
  analysis_run_id: string;
  status: InterviewSessionStatus;
  question_budget: number;
  questions_asked: number;
  current_turn_id: string | null;
  turns: InterviewTurnResponse[];
  derived_state: { risk_states: RiskState[] };
  final_report: FinalInterviewReport | null;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}
