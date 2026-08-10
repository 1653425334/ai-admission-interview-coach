"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";

import { ApiClientError, apiFetch } from "@/lib/api/client";
import type {
  AnalysisRunResponse,
  CandidateClaim,
  Evidence,
  InterviewMap,
  InterviewRisk,
} from "@/types/api";

const POLL_INTERVAL_MS = 2_000;

interface MaterialAnalysisPanelProps {
  applicationId: string;
  hasRequiredDocuments: boolean;
}

function analysisStorageKey(applicationId: string): string {
  return `analysis-run:${applicationId}`;
}

function safeAnalysisError(error: unknown): string {
  if (error instanceof ApiClientError && error.code === "ANALYSIS_DOCUMENTS_REQUIRED") {
    return "Upload one CV and one personal statement before starting analysis.";
  }
  return "Analysis could not be completed. Please try again.";
}

function stageLabel(stage: AnalysisRunResponse["stage"]): string {
  const labels: Record<AnalysisRunResponse["stage"], string> = {
    QUEUED: "Pending",
    PARSE_DOCUMENTS: "Reading CV and personal statement",
    BUILD_INTERVIEW_MAP: "Building interview map",
    COMPLETED: "Completed",
    FAILED: "Failed",
  };
  return labels[stage];
}

function riskEvidence(risk: InterviewRisk, evidenceById: Map<string, Evidence>): Evidence[] {
  return risk.evidence_ids.flatMap((evidenceId) => {
    const evidence = evidenceById.get(evidenceId);
    return evidence ? [evidence] : [];
  });
}

function CandidateOverview({ interviewMap }: { interviewMap: InterviewMap }) {
  const claimsById = new Map(interviewMap.claims.map((claim) => [claim.claim_id, claim]));
  const highValueClaims = interviewMap.candidate_profile.high_value_claim_ids.flatMap(
    (claimId): CandidateClaim[] => {
      const claim = claimsById.get(claimId);
      return claim ? [claim] : [];
    },
  );

  return (
    <section aria-labelledby="candidate-overview-heading" className="space-y-4 rounded-lg border p-5">
      <div>
        <h2 className="text-lg font-semibold" id="candidate-overview-heading">Candidate overview</h2>
        <p className="mt-2 leading-7">{interviewMap.candidate_profile.overview}</p>
      </div>
      <div>
        <h3 className="font-medium">Research interests</h3>
        {interviewMap.candidate_profile.research_interests.length > 0 ? (
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {interviewMap.candidate_profile.research_interests.map((interest) => (
              <li key={interest}>{interest}</li>
            ))}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-gray-600">No research interests were identified.</p>
        )}
      </div>
      <div>
        <h3 className="font-medium">High-value claims</h3>
        {highValueClaims.length > 0 ? (
          <ul className="mt-2 list-disc space-y-1 pl-5">
            {highValueClaims.map((claim) => <li key={claim.claim_id}>{claim.statement}</li>)}
          </ul>
        ) : (
          <p className="mt-2 text-sm text-gray-600">No high-value claims were identified.</p>
        )}
      </div>
    </section>
  );
}

function RiskCard({ risk, evidenceById }: { risk: InterviewRisk; evidenceById: Map<string, Evidence> }) {
  return (
    <article className="space-y-4 rounded-lg border p-5" aria-labelledby={`${risk.risk_id}-title`}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium text-gray-600">{risk.category}</p>
          <h3 className="text-lg font-semibold" id={`${risk.risk_id}-title`}>{risk.title}</h3>
        </div>
        <div className="text-right text-sm">
          <p>Severity: {risk.severity}/5</p>
          <p>Verification status: {risk.verification_status}</p>
        </div>
      </div>
      <div>
        <h4 className="font-medium">Evidence</h4>
        <ul className="mt-2 space-y-2">
          {riskEvidence(risk, evidenceById).map((evidence) => (
            <li className="rounded bg-gray-50 p-3 text-sm" key={evidence.evidence_id}>
              <p>“{evidence.original_text}”</p>
              <p className="mt-1 text-gray-600">{evidence.document_type}, page {evidence.location.page_number}</p>
            </li>
          ))}
        </ul>
      </div>
      <div>
        <h4 className="font-medium">Why verify this</h4>
        <p className="mt-1">{risk.reason}</p>
      </div>
      <div className="space-y-3">
        <h4 className="font-medium">Verification objectives</h4>
        {risk.objectives.map((objective) => (
          <div className="rounded bg-gray-50 p-3" key={objective.objective_id}>
            <p>{objective.verification_goal}</p>
            <p className="mt-2 text-sm font-medium">Coverage conditions</p>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-sm">
              {objective.coverage_conditions.map((condition) => (
                <li key={condition.condition_id}>{condition.description}{condition.required ? " (required)" : ""}</li>
              ))}
            </ul>
          </div>
        ))}
      </div>
      <dl className="grid gap-3 text-sm sm:grid-cols-2">
        <div>
          <dt className="font-medium">Suggested question types</dt>
          <dd className="mt-1">{risk.suggested_question_types.join(", ")}</dd>
        </div>
        <div>
          <dt className="font-medium">Maximum follow-ups</dt>
          <dd className="mt-1">{risk.max_followups}</dd>
        </div>
      </dl>
    </article>
  );
}

function InterviewMapView({ interviewMap }: { interviewMap: InterviewMap }) {
  const evidenceById = new Map(interviewMap.evidence.map((evidence) => [evidence.evidence_id, evidence]));
  const risksById = new Map(interviewMap.risks.map((risk) => [risk.risk_id, risk]));
  const orderedRisks = [
    ...interviewMap.priority_risk_ids.flatMap((riskId) => {
      const risk = risksById.get(riskId);
      return risk ? [risk] : [];
    }),
    ...interviewMap.risks.filter((risk) => !interviewMap.priority_risk_ids.includes(risk.risk_id)),
  ];

  return (
    <section aria-labelledby="interview-map-heading" className="space-y-4">
      <div>
        <h2 className="text-xl font-semibold" id="interview-map-heading">Interview map</h2>
        <p className="mt-1 text-sm text-gray-600">Evidence-grounded risks to verify in a future interview.</p>
      </div>
      {orderedRisks.length > 0 ? (
        <div className="space-y-4">
          {orderedRisks.map((risk) => <RiskCard evidenceById={evidenceById} key={risk.risk_id} risk={risk} />)}
        </div>
      ) : (
        <p className="rounded-lg border p-5 text-sm text-gray-600">No interview risks were identified.</p>
      )}
    </section>
  );
}

export default function MaterialAnalysisPanel({ applicationId, hasRequiredDocuments }: MaterialAnalysisPanelProps) {
  const router = useRouter();
  const [analysisRun, setAnalysisRun] = useState<AnalysisRunResponse | null>(null);
  const [loadingExisting, setLoadingExisting] = useState(hasRequiredDocuments);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(false);
  const requestSequence = useRef(0);
  const currentRunId = useRef<string | null>(null);

  const commitRun = useCallback((run: AnalysisRunResponse) => {
    currentRunId.current = run.id;
    setAnalysisRun(run);
    window.sessionStorage.setItem(analysisStorageKey(applicationId), run.id);
  }, [applicationId]);

  const handleApiError = useCallback((caught: unknown) => {
    if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
      router.replace("/sign-in");
      return;
    }
    setError(safeAnalysisError(caught));
  }, [router]);

  const refreshRun = useCallback(async (runId: string) => {
    const sequence = ++requestSequence.current;
    try {
      const run = await apiFetch<AnalysisRunResponse>(`/api/v1/analysis-runs/${runId}`);
      if (!mounted.current || sequence !== requestSequence.current || currentRunId.current !== runId) return;
      commitRun(run);
      setError(null);
    } catch (caught) {
      if (!mounted.current || sequence !== requestSequence.current || currentRunId.current !== runId) return;
      handleApiError(caught);
    }
  }, [commitRun, handleApiError]);

  const loadExistingAnalysis = useCallback(async () => {
    if (!hasRequiredDocuments) {
      currentRunId.current = null;
      setAnalysisRun(null);
      setError(null);
      return;
    }

    const sequence = ++requestSequence.current;
    setLoadingExisting(true);
    setError(null);
    const storedRunId = window.sessionStorage.getItem(analysisStorageKey(applicationId));
    try {
      if (storedRunId) {
        const storedRun = await apiFetch<AnalysisRunResponse>(`/api/v1/analysis-runs/${storedRunId}`);
        if (!mounted.current || sequence !== requestSequence.current) return;
        commitRun(storedRun);
        return;
      }

      const latestRun = await apiFetch<AnalysisRunResponse>(
        `/api/v1/applications/${applicationId}/latest-analysis`,
      );
      if (!mounted.current || sequence !== requestSequence.current) return;
      commitRun(latestRun);
    } catch (caught) {
      if (!mounted.current || sequence !== requestSequence.current) return;
      if (caught instanceof ApiClientError && caught.code === "AUTH_REQUIRED") {
        router.replace("/sign-in");
        return;
      }
      if (caught instanceof ApiClientError && caught.status === 404) {
        window.sessionStorage.removeItem(analysisStorageKey(applicationId));
        currentRunId.current = null;
        setAnalysisRun(null);
        return;
      }
      handleApiError(caught);
    } finally {
      if (mounted.current && sequence === requestSequence.current) setLoadingExisting(false);
    }
  }, [applicationId, commitRun, handleApiError, hasRequiredDocuments, router]);

  useEffect(() => {
    mounted.current = true;
    // The request only commits state asynchronously after the sequence guard.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void loadExistingAnalysis();
    return () => {
      mounted.current = false;
      requestSequence.current += 1;
    };
  }, [loadExistingAnalysis]);

  useEffect(() => {
    if (!analysisRun || (analysisRun.status !== "PENDING" && analysisRun.status !== "RUNNING")) return;
    const intervalId = window.setInterval(() => { void refreshRun(analysisRun.id); }, POLL_INTERVAL_MS);
    return () => window.clearInterval(intervalId);
  }, [analysisRun, refreshRun]);

  const startAnalysis = async () => {
    if (!hasRequiredDocuments || starting) return;
    requestSequence.current += 1;
    setStarting(true);
    setError(null);
    try {
      const run = await apiFetch<AnalysisRunResponse>(`/api/v1/applications/${applicationId}/analyses`, {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
      });
      if (!mounted.current) return;
      commitRun(run);
    } catch (caught) {
      if (!mounted.current) return;
      handleApiError(caught);
    } finally {
      if (mounted.current) setStarting(false);
    }
  };

  if (!hasRequiredDocuments) {
    return (
      <section className="space-y-3 rounded-lg border p-5" aria-labelledby="material-analysis-heading">
        <h2 className="text-lg font-semibold" id="material-analysis-heading">Material analysis</h2>
        <p>Upload one CV and one personal statement to analyse your application materials.</p>
      </section>
    );
  }

  const isActive = analysisRun?.status === "PENDING" || analysisRun?.status === "RUNNING";

  return (
    <section className="space-y-5" aria-labelledby="material-analysis-heading">
      <div className="space-y-3 rounded-lg border p-5">
        <div>
          <h2 className="text-lg font-semibold" id="material-analysis-heading">Material analysis</h2>
          <p className="mt-1 text-sm text-gray-600">Build an evidence-grounded interview map from your CV and personal statement.</p>
        </div>
        {loadingExisting ? <p role="status">Loading analysis status…</p> : null}
        {isActive ? (
          <div role="status">
            <p className="font-medium">{analysisRun.status.toLowerCase()}</p>
            <p className="text-sm text-gray-600">Current stage: {stageLabel(analysisRun.stage)}</p>
          </div>
        ) : analysisRun?.status === "FAILED" ? (
          <p className="text-sm text-red-700" role="alert">Analysis could not be completed. Please try again.</p>
        ) : null}
        {analysisRun?.status !== "COMPLETED" ? (
          <button
            className="rounded bg-black px-4 py-2 text-white disabled:opacity-60"
            disabled={starting || isActive || loadingExisting}
            onClick={() => { void startAnalysis(); }}
            type="button"
          >
            {starting ? "Starting analysis…" : analysisRun?.status === "FAILED" ? "Try analysis again" : "Analyse application materials"}
          </button>
        ) : null}
        {error ? <p className="text-sm text-red-700" role="alert">{error}</p> : null}
      </div>
      {analysisRun?.status === "COMPLETED" && analysisRun.interview_map ? (
        <>
          <CandidateOverview interviewMap={analysisRun.interview_map} />
          <InterviewMapView interviewMap={analysisRun.interview_map} />
        </>
      ) : null}
    </section>
  );
}
