import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type { InterviewSessionResponse, InterviewTurnResponse } from "@/types/api";

import MockInterviewPanel from "./mock-interview-panel";


const { router } = vi.hoisted(() => ({ router: { replace: vi.fn() } }));
vi.mock("next/navigation", () => ({ useRouter: () => router }));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...original, apiFetch: vi.fn() };
});

const mockApiFetch = vi.mocked(apiFetch);

function turn(overrides: Partial<InterviewTurnResponse> = {}): InterviewTurnResponse {
  return {
    id: "turn-1",
    sequence_number: 1,
    risk_id: "risk-1",
    objective_id: "objective-1",
    question_type: "EVIDENCE_PROBE",
    target_condition_ids: ["condition-1"],
    question_text: "How did you evaluate robustness?",
    followup_index: 0,
    parent_turn_id: null,
    answer_text: null,
    status: "ASKED",
    evaluation: null,
    asked_at: "2026-08-17T00:00:00Z",
    answered_at: null,
    ...overrides,
  };
}

function session(
  overrides: Partial<InterviewSessionResponse> = {},
): InterviewSessionResponse {
  return {
    id: "session-1",
    application_id: "app-1",
    analysis_run_id: "run-1",
    status: "ACTIVE",
    question_budget: 6,
    questions_asked: 1,
    current_turn_id: "turn-1",
    turns: [turn()],
    derived_state: {
      risk_states: [{
        risk_id: "risk-1",
        verification_status: "UNVERIFIED",
        objective_states: [{
          objective_id: "objective-1",
          condition_states: [{
            condition_id: "condition-1",
            latest_result: null,
            last_question_id: null,
          }],
          followups_used: 0,
          all_required_conditions_met: false,
          unresolved_required_condition_ids: ["condition-1"],
        }],
      }],
    },
    final_report: null,
    started_at: "2026-08-17T00:00:00Z",
    completed_at: null,
    created_at: "2026-08-17T00:00:00Z",
    ...overrides,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mockApiFetch.mockReset();
  window.sessionStorage.clear();
});

describe("MockInterviewPanel", () => {
  it("starts an interview and displays the first question", async () => {
    mockApiFetch.mockResolvedValueOnce(session());
    render(<MockInterviewPanel applicationId="app-1" />);

    await userEvent.click(await screen.findByRole("button", { name: "Start mock interview" }));

    expect(mockApiFetch).toHaveBeenCalledWith(
      "/api/v1/applications/app-1/interviews",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ question_budget: 6 }),
      },
    );
    expect(await screen.findByRole("heading", { name: "How did you evaluate robustness?" })).toBeInTheDocument();
    expect(screen.getByText("Question 1 of up to 6")).toBeInTheDocument();
    expect(window.sessionStorage.getItem("interview-session:app-1")).toBe("session-1");
  });

  it("submits an answer and renders its evaluation plus the targeted follow-up", async () => {
    const first = session();
    const evaluatedFirst = turn({
      answer_text: "We tested Gaussian noise.",
      status: "EVALUATED",
      evaluation: {
        question_id: "turn-1",
        risk_id: "risk-1",
        objective_id: "objective-1",
        condition_results: [{
          condition_id: "condition-1",
          result: "MET",
          answer_excerpt: "We tested Gaussian noise.",
          reason: "The answer names a robustness test.",
        }],
        unmet_required_condition_ids: ["condition-2"],
        strengths: ["Names a concrete test."],
        missing_points: ["Give a baseline result."],
        unsupported_claims: [],
        communication_feedback: null,
      },
    });
    const followup = turn({
      id: "turn-2",
      sequence_number: 2,
      target_condition_ids: ["condition-2"],
      question_text: "What result did you observe against the baseline?",
      followup_index: 1,
      parent_turn_id: "turn-1",
    });
    mockApiFetch
      .mockResolvedValueOnce(first)
      .mockResolvedValueOnce(session({
        questions_asked: 2,
        current_turn_id: "turn-2",
        turns: [evaluatedFirst, followup],
      }));
    render(<MockInterviewPanel applicationId="app-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Start mock interview" }));
    await userEvent.type(screen.getByLabelText("Your answer"), "We tested Gaussian noise.");
    await userEvent.click(screen.getByRole("button", { name: "Submit answer" }));

    expect(mockApiFetch).toHaveBeenLastCalledWith(
      "/api/v1/interviews/session-1/turns",
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ turn_id: "turn-1", answer_text: "We tested Gaussian noise." }),
      },
    );
    expect(await screen.findByRole("heading", { name: "What result did you observe against the baseline?" })).toBeInTheDocument();
    expect(screen.getByText("MET").closest("li")).toHaveTextContent(
      "MET: The answer names a robustness test.",
    );
    expect(screen.getByText(/Give a baseline result/)).toBeInTheDocument();
  });

  it("restores a stored interview after refresh", async () => {
    window.sessionStorage.setItem("interview-session:app-1", "session-1");
    mockApiFetch.mockResolvedValueOnce(session());
    render(<MockInterviewPanel applicationId="app-1" />);

    expect(await screen.findByRole("heading", { name: "How did you evaluate robustness?" })).toBeInTheDocument();
    expect(mockApiFetch).toHaveBeenCalledWith("/api/v1/interviews/session-1");
    expect(screen.queryByRole("button", { name: "Start mock interview" })).not.toBeInTheDocument();
  });

  it("shows a completed report and can start another interview", async () => {
    window.sessionStorage.setItem("interview-session:app-1", "session-1");
    mockApiFetch.mockResolvedValueOnce(session({
      status: "COMPLETED",
      current_turn_id: null,
      completed_at: "2026-08-17T00:05:00Z",
      turns: [turn({ answer_text: "A complete answer.", status: "EVALUATED" })],
      final_report: {
        overall_summary: "Verified one interview risk.",
        strong_answers: ["Robustness evidence"],
        unresolved_risks: [],
        preparation_recommendations: ["Keep the result concise."],
        english_communication_feedback: null,
      },
    }));
    render(<MockInterviewPanel applicationId="app-1" />);

    expect(await screen.findByRole("heading", { name: "Interview report" })).toBeInTheDocument();
    expect(screen.getByText("Verified one interview risk.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start another interview" })).toBeEnabled();
  });

  it("shows only safe API errors", async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiClientError("INTERNAL_ERROR", "provider key sk-private", "request-secret", 500),
    );
    render(<MockInterviewPanel applicationId="app-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Start mock interview" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The interview request could not be completed. Please try again.",
    );
    expect(screen.queryByText(/sk-private/)).not.toBeInTheDocument();
    expect(screen.queryByText(/request-secret/)).not.toBeInTheDocument();
  });

  it("explains when material analysis is not ready", async () => {
    mockApiFetch.mockRejectedValueOnce(
      new ApiClientError("INTERVIEW_MAP_REQUIRED", "unsafe details", "request-1", 409),
    );
    render(<MockInterviewPanel applicationId="app-1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Start mock interview" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Complete material analysis and identify at least one interview risk first.",
    );
  });
});
