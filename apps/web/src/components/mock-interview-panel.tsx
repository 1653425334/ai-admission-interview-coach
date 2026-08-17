"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type {
  AnswerEvaluation,
  FinalInterviewReport,
  InterviewSessionResponse,
  InterviewTurnResponse,
} from "@/types/api";


interface MockInterviewPanelProps {
  applicationId: string;
}

function interviewStorageKey(applicationId: string): string {
  return `interview-session:${applicationId}`;
}

function safeInterviewError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "INTERVIEW_MAP_REQUIRED") {
    return "Complete material analysis and identify at least one interview risk first.";
  }
  if (error instanceof ApiClientError && error.code === "INTERVIEW_TURN_CONFLICT") {
    return "This question has already changed. Refresh the interview and try again.";
  }
  return "The interview request could not be completed. Please try again.";
}

function EvaluationView({ evaluation }: { evaluation: AnswerEvaluation }) {
  return (
    <div className="space-y-3 rounded bg-gray-50 p-4 text-sm">
      <h4 className="font-medium">Answer evaluation</h4>
      <ul className="space-y-2">
        {evaluation.condition_results.map((result) => (
          <li key={result.condition_id}>
            <span className="font-medium">{result.result}</span>: {result.reason}
          </li>
        ))}
      </ul>
      {evaluation.strengths.length > 0 ? (
        <p><span className="font-medium">Strengths:</span> {evaluation.strengths.join(" ")}</p>
      ) : null}
      {evaluation.missing_points.length > 0 ? (
        <p><span className="font-medium">Missing:</span> {evaluation.missing_points.join(" ")}</p>
      ) : null}
    </div>
  );
}

function PreviousTurn({ turn }: { turn: InterviewTurnResponse }) {
  return (
    <article className="space-y-3 rounded-lg border p-4">
      <p className="text-sm font-medium text-gray-600">Question {turn.sequence_number}</p>
      <p className="font-medium">{turn.question_text}</p>
      {turn.answer_text ? <p><span className="font-medium">Your answer:</span> {turn.answer_text}</p> : null}
      {turn.evaluation ? <EvaluationView evaluation={turn.evaluation} /> : null}
    </article>
  );
}

function InterviewReport({ report }: { report: FinalInterviewReport }) {
  return (
    <section className="space-y-4 rounded-lg border p-5" aria-labelledby="interview-report-heading">
      <h3 className="text-lg font-semibold" id="interview-report-heading">Interview report</h3>
      <p>{report.overall_summary}</p>
      <ReportList items={report.strong_answers} title="Strong answers" empty="No risks were fully verified." />
      <ReportList items={report.unresolved_risks} title="Unresolved risks" empty="No unresolved risks." />
      <ReportList items={report.preparation_recommendations} title="Preparation recommendations" empty="No additional recommendations." />
    </section>
  );
}

function ReportList({ items, title, empty }: { items: string[]; title: string; empty: string }) {
  return (
    <div>
      <h4 className="font-medium">{title}</h4>
      {items.length > 0 ? (
        <ul className="mt-2 list-disc space-y-1 pl-5">{items.map((item) => <li key={item}>{item}</li>)}</ul>
      ) : <p className="mt-1 text-sm text-gray-600">{empty}</p>}
    </div>
  );
}

export default function MockInterviewPanel({ applicationId }: MockInterviewPanelProps) {
  const router = useRouter();
  const [interview, setInterview] = useState<InterviewSessionResponse | null>(null);
  const [answer, setAnswer] = useState("");
  const [loading, setLoading] = useState(true);
  const [starting, setStarting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const requestSequence = useRef(0);

  const handleError = useCallback((caught: unknown) => {
    if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
      router.replace("/sign-in");
      return;
    }
    setError(safeInterviewError(caught));
  }, [router]);

  const commitInterview = useCallback((value: InterviewSessionResponse) => {
    setInterview(value);
    window.sessionStorage.setItem(interviewStorageKey(applicationId), value.id);
  }, [applicationId]);

  useEffect(() => {
    mounted.current = true;
    const sequence = ++requestSequence.current;
    const storedId = window.sessionStorage.getItem(interviewStorageKey(applicationId));
    if (!storedId) {
      void Promise.resolve().then(() => {
        if (mounted.current && sequence === requestSequence.current) setLoading(false);
      });
      return () => {
        mounted.current = false;
        requestSequence.current += 1;
      };
    }
    void apiFetch<InterviewSessionResponse>(`/api/v1/interviews/${storedId}`)
      .then((value) => {
        if (!mounted.current || sequence !== requestSequence.current) return;
        commitInterview(value);
      })
      .catch((caught: unknown) => {
        if (!mounted.current || sequence !== requestSequence.current) return;
        if (caught instanceof ApiClientError && caught.status === 404) {
          window.sessionStorage.removeItem(interviewStorageKey(applicationId));
          setInterview(null);
          return;
        }
        handleError(caught);
      })
      .finally(() => {
        if (mounted.current && sequence === requestSequence.current) setLoading(false);
      });
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, [applicationId, commitInterview, handleError]);

  const startInterview = async () => {
    if (starting) return;
    const sequence = ++requestSequence.current;
    setStarting(true);
    setError(null);
    try {
      const value = await apiFetch<InterviewSessionResponse>(
        `/api/v1/applications/${applicationId}/interviews`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ question_budget: 6 }),
        },
      );
      if (!mounted.current || sequence !== requestSequence.current) return;
      commitInterview(value);
      setAnswer("");
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current) handleError(caught);
    } finally {
      if (mounted.current && sequence === requestSequence.current) setStarting(false);
    }
  };

  const submitAnswer = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const currentTurnId = interview?.current_turn_id;
    if (!currentTurnId || !answer.trim() || submitting) return;
    const sequence = ++requestSequence.current;
    setSubmitting(true);
    setError(null);
    try {
      const value = await apiFetch<InterviewSessionResponse>(
        `/api/v1/interviews/${interview.id}/turns`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ turn_id: currentTurnId, answer_text: answer.trim() }),
        },
      );
      if (!mounted.current || sequence !== requestSequence.current) return;
      commitInterview(value);
      setAnswer("");
    } catch (caught) {
      if (mounted.current && sequence === requestSequence.current) handleError(caught);
    } finally {
      if (mounted.current && sequence === requestSequence.current) setSubmitting(false);
    }
  };

  const currentTurn = interview?.turns.find((turn) => turn.id === interview.current_turn_id) ?? null;
  const previousTurns = interview?.turns.filter((turn) => turn.id !== interview.current_turn_id) ?? [];

  return (
    <section className="space-y-5" aria-labelledby="mock-interview-heading">
      <div className="space-y-3 rounded-lg border p-5">
        <div>
          <h2 className="text-lg font-semibold" id="mock-interview-heading">Adaptive mock interview</h2>
          <p className="mt-1 text-sm text-gray-600">Practise one question at a time against the risks in your Interview Map.</p>
        </div>
        {loading ? <p role="status">Loading interview…</p> : null}
        {!loading && (!interview || interview.status === "COMPLETED") ? (
          <button
            className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
            disabled={starting}
            onClick={() => { void startInterview(); }}
            type="button"
          >
            {starting ? "Starting interview…" : interview ? "Start another interview" : "Start mock interview"}
          </button>
        ) : null}
        {interview?.status === "ACTIVE" ? (
          <p className="text-sm text-gray-600" role="status">Question {interview.questions_asked} of up to {interview.question_budget}</p>
        ) : null}
        {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
      </div>

      {previousTurns.length > 0 ? (
        <div className="space-y-3" aria-label="Previous interview turns">
          {previousTurns.map((turn) => <PreviousTurn key={turn.id} turn={turn} />)}
        </div>
      ) : null}

      {interview?.status === "ACTIVE" && currentTurn ? (
        <form className="space-y-4 rounded-lg border p-5" onSubmit={(event) => { void submitAnswer(event); }}>
          <div>
            <p className="text-sm font-medium text-gray-600">Current question · {currentTurn.question_type}</p>
            <h3 className="mt-2 text-lg font-semibold">{currentTurn.question_text}</h3>
          </div>
          <label className="block space-y-2">
            <span className="font-medium">Your answer</span>
            <textarea
              className="min-h-40 w-full rounded border p-3"
              maxLength={8000}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder="Answer with concrete examples, decisions, and results."
              value={answer}
            />
          </label>
          <button
            className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
            disabled={submitting || !answer.trim()}
            type="submit"
          >
            {submitting ? "Evaluating answer…" : "Submit answer"}
          </button>
        </form>
      ) : null}

      {interview?.status === "COMPLETED" && interview.final_report ? (
        <InterviewReport report={interview.final_report} />
      ) : null}
    </section>
  );
}
