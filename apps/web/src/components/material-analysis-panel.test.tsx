import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { AnalysisRunResponse, InterviewMap } from "@/types/api";

import MaterialAnalysisPanel from "./material-analysis-panel";

const { router } = vi.hoisted(() => {
  const replace = vi.fn();
  return { router: { replace } };
});
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

const interviewMap: InterviewMap = {
  schema_version: "interview-map-v1",
  analysis_run_id: "run-1",
  candidate_profile: {
    overview: "The candidate describes an attention-based robustness project.",
    research_interests: ["Robust machine learning"],
    high_value_claim_ids: ["claim-robustness"],
    missing_or_uncertain_information: [],
  },
  evidence: [{
    evidence_id: "evidence-cv-project",
    source_type: "APPLICATION_DOCUMENT",
    document_id: "doc-cv",
    document_type: "CV",
    location: { page_number: 1, section: "Projects", start_offset: 0, end_offset: 42 },
    original_text: "Developed an attention-based model to improve robustness.",
  }],
  input_manifest: [{
    document_id: "doc-cv",
    document_type: "CV",
    sha256: "a".repeat(64),
    page_count: 1,
  }, {
    document_id: "doc-ps",
    document_type: "PS",
    sha256: "b".repeat(64),
    page_count: 1,
  }],
  claims: [{
    claim_id: "claim-robustness",
    category: "PERFORMANCE_IMPROVEMENT",
    statement: "The proposed method improved robustness.",
    assertion_strength: "EXPLICIT",
    evidence_ids: ["evidence-cv-project"],
    interview_value: "HIGH",
  }],
  risks: [{
    risk_id: "risk-robustness-evidence",
    category: "EVIDENCE_GAP",
    severity: 4,
    title: "Robustness improvement needs evidence",
    evidence_ids: ["evidence-cv-project"],
    claim_id: "claim-robustness",
    reason: "The material does not identify the robustness test or baseline.",
    objectives: [{
      objective_id: "objective-robustness",
      risk_id: "risk-robustness-evidence",
      target_claim_id: "claim-robustness",
      verification_goal: "Verify the candidate can define and evaluate robustness.",
      coverage_conditions: [{
        condition_id: "condition-test",
        type: "NAMES_TEST",
        description: "Names the robustness or perturbation test.",
        required: true,
      }],
    }],
    suggested_question_types: ["EVIDENCE_PROBE", "TECHNICAL_DEPTH_PROBE"],
    max_followups: 2,
    verification_status: "UNVERIFIED",
  }],
  priority_risk_ids: ["risk-robustness-evidence"],
};

function run(status: AnalysisRunResponse["status"], interview_map: InterviewMap | null = null): AnalysisRunResponse {
  return {
    id: "run-1",
    application_id: "app-1",
    status,
    stage: status === "PENDING" ? "QUEUED" : status === "RUNNING" ? "PARSE_DOCUMENTS" : status === "COMPLETED" ? "COMPLETED" : "FAILED",
    error_code: status === "FAILED" ? "ANALYSIS_FAILED" : null,
    error_message: status === "FAILED" ? "private parser path" : null,
    created_at: "2026-08-10T00:00:00Z",
    started_at: null,
    completed_at: status === "COMPLETED" ? "2026-08-10T00:01:00Z" : null,
    interview_map,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApiFetch.mockReset();
  window.sessionStorage.clear();
});

describe("MaterialAnalysisPanel", () => {
  it("does not allow analysis before both CV and personal statement are present", () => {
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments={false} />);
    expect(screen.getByText("Upload one CV and one personal statement to analyse your application materials.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /analyse application materials/i })).not.toBeInTheDocument();
    expect(mockApiFetch).not.toHaveBeenCalled();
  });

  it("creates an analysis run when the user starts analysis", async () => {
    mockApiFetch
      .mockRejectedValueOnce(new ApiClientError("ANALYSIS_NOT_FOUND", "No current analysis.", "req-1", 404))
      .mockResolvedValueOnce(run("PENDING"));
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);

    const start = screen.getByRole("button", { name: "Analyse application materials" });
    await vi.waitFor(() => expect(start).toBeEnabled());
    await userEvent.click(start);

    expect(mockApiFetch).toHaveBeenNthCalledWith(
      2,
      "/api/v1/applications/app-1/analyses",
      expect.objectContaining({ method: "POST", headers: expect.objectContaining({ "Idempotency-Key": expect.any(String) }) }),
    );
    expect(await screen.findByText("pending")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("analysis-run:app-1")).toBe("run-1");
  });

  it("shows pending and running stages returned by the API", async () => {
    mockApiFetch.mockResolvedValueOnce(run("PENDING"));
    const view = render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);
    expect(await screen.findByText("pending")).toBeInTheDocument();
    expect(screen.getByText("Current stage: Pending")).toBeInTheDocument();
    view.unmount();

    window.sessionStorage.clear();
    mockApiFetch.mockReset();
    mockApiFetch.mockResolvedValueOnce(run("RUNNING"));
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);
    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(screen.getByText("Current stage: Reading CV and personal statement")).toBeInTheDocument();
  });

  it("shows the candidate overview and risk cards for a completed analysis", async () => {
    mockApiFetch.mockResolvedValueOnce(run("COMPLETED", interviewMap));
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);

    expect(await screen.findByRole("heading", { name: "Candidate overview" })).toBeInTheDocument();
    expect(screen.getByText("Robust machine learning")).toBeInTheDocument();
    expect(screen.getByText("The proposed method improved robustness.")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Interview map" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Robustness improvement needs evidence" })).toBeInTheDocument();
    expect(screen.getByText("EVIDENCE_GAP")).toBeInTheDocument();
    expect(screen.getByText("Verification status: UNVERIFIED")).toBeInTheDocument();
    expect(screen.getByText("Names the robustness or perturbation test. (required)")).toBeInTheDocument();
  });

  it("shows a safe failure message and allows a retry", async () => {
    mockApiFetch.mockResolvedValueOnce(run("FAILED"));
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Analysis could not be completed. Please try again.");
    expect(screen.queryByText("private parser path")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Try analysis again" })).toBeEnabled();
  });

  it("restores the stored analysis run after a page refresh", async () => {
    window.sessionStorage.setItem("analysis-run:app-1", "run-1");
    mockApiFetch.mockResolvedValueOnce(run("RUNNING"));
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);

    expect(await screen.findByText("running")).toBeInTheDocument();
    expect(mockApiFetch).toHaveBeenCalledWith("/api/v1/analysis-runs/run-1");
    expect(mockApiFetch).not.toHaveBeenCalledWith("/api/v1/applications/app-1/latest-analysis");
  });

  it("does not expose an API error message", async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiClientError("API_ERROR", "storage key: private/material.pdf", "req-private", 500),
    );
    render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Analysis could not be completed. Please try again.");
    expect(screen.queryByText(/private\/material\.pdf/)).not.toBeInTheDocument();
    expect(screen.queryByText("req-private")).not.toBeInTheDocument();
  });

  it("stops polling when the panel unmounts", async () => {
    vi.useFakeTimers();
    try {
      mockApiFetch.mockResolvedValue(run("PENDING"));
      const view = render(<MaterialAnalysisPanel applicationId="app-1" hasRequiredDocuments />);
      await act(async () => { await Promise.resolve(); });
      expect(screen.getByText("pending")).toBeInTheDocument();
      await act(async () => { await vi.advanceTimersByTimeAsync(2_000); });
      expect(mockApiFetch).toHaveBeenCalledTimes(2);

      view.unmount();
      await act(async () => { await vi.advanceTimersByTimeAsync(4_000); });
      expect(mockApiFetch).toHaveBeenCalledTimes(2);
    } finally {
      vi.useRealTimers();
    }
  });
});
